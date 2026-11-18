package io.github.snowjug.sparta.data.remote

import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Response
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory

/** The owner-configured backend, or null before onboarding. Read on every request so a URL change applies at once. */
fun interface BaseUrlProvider {
    fun current(): HttpUrl?
}

/**
 * Auth seam. Development backends need no credentials (the identity banner is shown instead).
 * Production OIDC (Microsoft Entra External ID) sign-in is NOT integrated in this app: until a real provider is
 * implemented this stays [NoAuthTokenProvider], and a backend that demands a token answers 401, which the UI reports.
 */
fun interface AuthTokenProvider {
    fun accessToken(): String?
}

object NoAuthTokenProvider : AuthTokenProvider {
    override fun accessToken(): String? = null
}

/** Marks requests whose URL is already absolute (WebSocket handshakes) so they bypass base-URL rewriting. */
object AbsoluteUrl

/** Retrofit builds URLs against a placeholder host; this swaps in the configured backend (scheme, host, port, path prefix). */
class DynamicBaseUrlInterceptor(private val provider: BaseUrlProvider) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        if (request.tag(AbsoluteUrl::class.java) != null) return chain.proceed(request)

        val base = provider.current() ?: throw BackendNotConfiguredException()
        val original = request.url
        val target = base.newBuilder()
            .addEncodedPathSegments(original.encodedPath.trimStart('/'))
            .encodedQuery(original.encodedQuery)
            .build()
        return chain.proceed(request.newBuilder().url(target).build())
    }
}

class HeadersInterceptor(
    private val tokens: AuthTokenProvider,
    private val userAgent: String,
) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val builder = chain.request().newBuilder()
            .header("Accept", "application/json")
            .header("User-Agent", userAgent)
        if (chain.request().header("X-Request-ID") == null) {
            builder.header("X-Request-ID", UUID.randomUUID().toString())
        }
        tokens.accessToken()?.let { builder.header("Authorization", "Bearer $it") }
        return chain.proceed(builder.build())
    }
}

object NetworkFactory {
    /** Host used only to satisfy Retrofit; [DynamicBaseUrlInterceptor] replaces it on every request. */
    const val PLACEHOLDER_BASE = "https://sparta.invalid/"

    fun createClient(
        baseUrl: BaseUrlProvider,
        tokens: AuthTokenProvider = NoAuthTokenProvider,
        userAgent: String = "SpartaAndroid",
        configure: OkHttpClient.Builder.() -> Unit = {},
    ): OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(25, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        .callTimeout(40, TimeUnit.SECONDS)
        .followRedirects(false)
        .followSslRedirects(false)
        .addInterceptor(DynamicBaseUrlInterceptor(baseUrl))
        .addInterceptor(HeadersInterceptor(tokens, userAgent))
        .apply(configure)
        .build()

    fun createApi(client: OkHttpClient, json: Json = SpartaJson): SpartaApi = Retrofit.Builder()
        .baseUrl(PLACEHOLDER_BASE)
        .client(client)
        .addConverterFactory(json.asConverterFactory("application/json; charset=UTF-8".toMediaType()))
        .build()
        .create(SpartaApi::class.java)
}
