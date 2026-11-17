package io.github.snowjug.sparta.data.remote

import io.github.snowjug.sparta.data.remote.dto.AssistantPreviewDto
import io.github.snowjug.sparta.data.remote.dto.AssistantPreviewRequestDto
import io.github.snowjug.sparta.data.remote.dto.BlockRequestDto
import io.github.snowjug.sparta.data.remote.dto.BlockedCallerDto
import io.github.snowjug.sparta.data.remote.dto.CallDetailDto
import io.github.snowjug.sparta.data.remote.dto.CallListItemDto
import io.github.snowjug.sparta.data.remote.dto.CallPageDto
import io.github.snowjug.sparta.data.remote.dto.EmptyBody
import io.github.snowjug.sparta.data.remote.dto.FeedbackRecordDto
import io.github.snowjug.sparta.data.remote.dto.FeedbackRequestDto
import io.github.snowjug.sparta.data.remote.dto.HomeSummaryDto
import io.github.snowjug.sparta.data.remote.dto.LiveEventDto
import io.github.snowjug.sparta.data.remote.dto.LiveTicketDto
import io.github.snowjug.sparta.data.remote.dto.LiveTicketRequestDto
import io.github.snowjug.sparta.data.remote.dto.MeDto
import io.github.snowjug.sparta.data.remote.dto.OwnerActionResultDto
import io.github.snowjug.sparta.data.remote.dto.SafetyPolicyDto
import io.github.snowjug.sparta.data.remote.dto.ScreeningConfigDto
import io.github.snowjug.sparta.data.remote.dto.ScreeningEventRequestDto
import io.github.snowjug.sparta.data.remote.dto.ScreeningListsDto
import io.github.snowjug.sparta.data.remote.dto.SystemStatusDto
import io.github.snowjug.sparta.data.remote.dto.TrustRequestDto
import io.github.snowjug.sparta.data.remote.dto.TrustedCallerDto
import io.github.snowjug.sparta.data.remote.dto.VoiceConsentDto
import io.github.snowjug.sparta.data.remote.dto.VoiceOptionDto
import io.github.snowjug.sparta.data.remote.dto.VoiceProfileViewDto
import kotlinx.serialization.json.JsonObject
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * Sparta backend (docs/API_CONTRACT.md). Paths are relative to the configured base URL; the base-URL interceptor
 * resolves them, so only the owner's chosen backend is ever contacted. Calls throw; use [safeApiCall].
 *
 * Preferences and the assistant profile are PUT as whole documents (the backend replaces them), so they travel as
 * raw [JsonObject]s: unknown fields round-trip untouched instead of being reset by an older client.
 */
interface SpartaApi {
    @GET("api/v1/system/status")
    suspend fun systemStatus(): SystemStatusDto

    @GET("api/v1/me")
    suspend fun me(): MeDto

    @GET("api/v1/home")
    suspend fun home(): HomeSummaryDto

    @GET("api/v1/safety/policies")
    suspend fun safetyPolicy(): SafetyPolicyDto

    @GET("api/v1/calls")
    suspend fun calls(
        @Query("q") query: String? = null,
        @Query("risk_level") riskLevel: String? = null,
        @Query("category") category: String? = null,
        @Query("language") language: String? = null,
        @Query("status") status: String? = null,
        @Query("attention") attention: Boolean? = null,
        @Query("limit") limit: Int? = null,
        @Query("cursor") cursor: String? = null,
    ): CallPageDto

    @GET("api/v1/calls/{id}")
    suspend fun call(@Path("id") id: String): CallDetailDto

    @GET("api/v1/calls/{id}/events")
    suspend fun callEvents(@Path("id") id: String, @Query("after_seq") afterSeq: Long? = null): List<LiveEventDto>

    @POST("api/v1/calls/{id}/takeover")
    suspend fun takeover(
        @Path("id") id: String,
        @Header("Idempotency-Key") idempotencyKey: String? = null,
        @Body body: EmptyBody = EmptyBody(),
    ): OwnerActionResultDto

    @POST("api/v1/calls/{id}/continue")
    suspend fun continueCall(
        @Path("id") id: String,
        @Header("Idempotency-Key") idempotencyKey: String? = null,
        @Body body: EmptyBody = EmptyBody(),
    ): OwnerActionResultDto

    @POST("api/v1/calls/{id}/end")
    suspend fun endCall(
        @Path("id") id: String,
        @Header("Idempotency-Key") idempotencyKey: String? = null,
        @Body body: EmptyBody = EmptyBody(),
    ): OwnerActionResultDto

    @POST("api/v1/calls/{id}/block")
    suspend fun blockCaller(
        @Path("id") id: String,
        @Header("Idempotency-Key") idempotencyKey: String? = null,
        @Body body: BlockRequestDto = BlockRequestDto(),
    ): BlockedCallerDto

    @POST("api/v1/calls/{id}/trust")
    suspend fun trustCaller(
        @Path("id") id: String,
        @Header("Idempotency-Key") idempotencyKey: String? = null,
        @Body body: TrustRequestDto = TrustRequestDto(),
    ): TrustedCallerDto

    @POST("api/v1/calls/{id}/feedback")
    suspend fun feedback(@Path("id") id: String, @Body body: FeedbackRequestDto): FeedbackRecordDto

    @DELETE("api/v1/calls/{id}/content")
    suspend fun deleteCallContent(@Path("id") id: String)

    @DELETE("api/v1/calls/{id}")
    suspend fun deleteCall(@Path("id") id: String)

    @DELETE("api/v1/calls")
    suspend fun deleteAllCalls()

    @GET("api/v1/preferences")
    suspend fun preferences(): JsonObject

    @PUT("api/v1/preferences")
    suspend fun putPreferences(@Body body: JsonObject): JsonObject

    @GET("api/v1/assistant-profile")
    suspend fun assistantProfile(): JsonObject

    @PUT("api/v1/assistant-profile")
    suspend fun putAssistantProfile(@Body body: JsonObject): JsonObject

    @POST("api/v1/assistant-profile/preview")
    suspend fun previewAssistant(@Body body: AssistantPreviewRequestDto): AssistantPreviewDto

    @GET("api/v1/voices")
    suspend fun voices(): List<VoiceOptionDto>

    @GET("api/v1/voice/status")
    suspend fun voiceStatus(): VoiceProfileViewDto

    @GET("api/v1/voice/consent")
    suspend fun voiceConsent(): VoiceConsentDto

    @GET("api/v1/blocked-callers")
    suspend fun blockedCallers(): List<BlockedCallerDto>

    @DELETE("api/v1/blocked-callers/{id}")
    suspend fun removeBlockedCaller(@Path("id") id: String)

    @GET("api/v1/trusted-callers")
    suspend fun trustedCallers(): List<TrustedCallerDto>

    @DELETE("api/v1/trusted-callers/{id}")
    suspend fun removeTrustedCaller(@Path("id") id: String)

    @GET("api/v1/screening/config")
    suspend fun screeningConfig(): ScreeningConfigDto

    @GET("api/v1/screening/lists")
    suspend fun screeningLists(): ScreeningListsDto

    @POST("api/v1/screening/events")
    suspend fun postScreeningEvent(
        @Header("Idempotency-Key") idempotencyKey: String,
        @Body body: ScreeningEventRequestDto,
    ): CallListItemDto

    @POST("api/v1/live/ticket")
    suspend fun liveTicket(@Body body: LiveTicketRequestDto): LiveTicketDto
}
