package io.github.snowjug.sparta.testutil

import io.github.snowjug.sparta.data.remote.AuthTokenProvider
import io.github.snowjug.sparta.data.remote.BaseUrlProvider
import io.github.snowjug.sparta.data.remote.NetworkFactory
import io.github.snowjug.sparta.data.remote.NoAuthTokenProvider
import io.github.snowjug.sparta.data.remote.SpartaApi
import okhttp3.HttpUrl
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest

/**
 * The real Retrofit client pointed at a MockWebServer. [reachable] lets a test model "no backend configured": while it
 * returns false the client behaves like production does without a saved address (the request never leaves the app).
 */
class ApiHarness(
    tokens: AuthTokenProvider = NoAuthTokenProvider,
    basePath: String = "/",
    reachable: () -> Boolean = { true },
    configure: OkHttpClient.Builder.() -> Unit = {},
) : AutoCloseable {
    val server = MockWebServer().also { it.start() }
    val baseUrl: HttpUrl = server.url(basePath)
    val client: OkHttpClient = NetworkFactory.createClient(BaseUrlProvider { if (reachable()) baseUrl else null }, tokens, "SpartaAndroidTest/1.0", configure)
    val api: SpartaApi = NetworkFactory.createApi(client)

    fun enqueueJson(body: String, code: Int = 200, vararg headers: Pair<String, String>) {
        val response = MockResponse().setResponseCode(code).setHeader("Content-Type", "application/json").setBody(body)
        headers.forEach { (name, value) -> response.setHeader(name, value) }
        server.enqueue(response)
    }

    fun enqueueEmpty(code: Int) {
        server.enqueue(MockResponse().setResponseCode(code))
    }

    /**
     * Answers by path (any method), so a flow that fires several requests does not depend on their order.
     * Paths that are not listed get a 404 error envelope.
     */
    fun serve(vararg routes: Pair<String, String>) {
        val byPath = routes.toMap()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val body = byPath[request.path.orEmpty().substringBefore('?')]
                val response = MockResponse().setHeader("Content-Type", "application/json")
                return if (body != null) {
                    response.setResponseCode(200).setBody(body)
                } else {
                    response.setResponseCode(404).setBody("""{"error":{"code":"not_found","message":"No route","trace_id":"t"}}""")
                }
            }
        }
    }

    fun takeRequest(): RecordedRequest = requireNotNull(server.takeRequest(5, java.util.concurrent.TimeUnit.SECONDS)) { "no request received" }

    override fun close() {
        runCatching { server.shutdown() }
    }
}
