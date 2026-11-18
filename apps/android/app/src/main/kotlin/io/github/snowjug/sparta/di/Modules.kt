package io.github.snowjug.sparta.di

import android.content.Context
import android.os.SystemClock
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.preferencesDataStoreFile
import androidx.room.Room
import androidx.work.WorkManager
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import io.github.snowjug.sparta.BuildConfig
import io.github.snowjug.sparta.core.net.BackendUrlPolicy
import io.github.snowjug.sparta.core.live.LiveCallReducer
import io.github.snowjug.sparta.core.screening.LocalFactsGatherer
import io.github.snowjug.sparta.core.screening.MonotonicClock
import io.github.snowjug.sparta.core.screening.ScreeningCoordinator
import io.github.snowjug.sparta.core.screening.ScreeningDecisionEngine
import io.github.snowjug.sparta.core.time.IdGenerator
import io.github.snowjug.sparta.core.time.MinuteOfDayProvider
import io.github.snowjug.sparta.core.time.WallClock
import io.github.snowjug.sparta.data.local.CachedCallDao
import io.github.snowjug.sparta.data.local.ListEntryDao
import io.github.snowjug.sparta.data.local.NotifiedItemDao
import io.github.snowjug.sparta.data.local.ScreeningEventDao
import io.github.snowjug.sparta.data.local.SpartaDatabase
import io.github.snowjug.sparta.data.prefs.DataStoreSettingsRepository
import io.github.snowjug.sparta.data.prefs.SettingsRepository
import io.github.snowjug.sparta.data.remote.AuthTokenProvider
import io.github.snowjug.sparta.data.remote.BaseUrlProvider
import io.github.snowjug.sparta.data.remote.NetworkFactory
import io.github.snowjug.sparta.data.remote.NoAuthTokenProvider
import io.github.snowjug.sparta.data.remote.SpartaApi
import io.github.snowjug.sparta.data.remote.SpartaJson
import io.github.snowjug.sparta.data.remote.ws.LiveCallClient
import io.github.snowjug.sparta.data.remote.ws.LiveEventSource
import io.github.snowjug.sparta.data.repo.BackendConnector
import io.github.snowjug.sparta.data.repo.BackgroundSync
import io.github.snowjug.sparta.data.repo.CallsRepository
import io.github.snowjug.sparta.data.repo.ConnectionTester
import io.github.snowjug.sparta.data.repo.EscalationAnnouncer
import io.github.snowjug.sparta.data.repo.EscalationMonitor
import io.github.snowjug.sparta.data.repo.EscalationNotifier
import io.github.snowjug.sparta.data.repo.LiveCallSession
import io.github.snowjug.sparta.data.repo.PermissionModel
import io.github.snowjug.sparta.data.repo.PreferencesRepository
import io.github.snowjug.sparta.data.repo.RoomScreeningLists
import io.github.snowjug.sparta.data.repo.ScreeningNotifier
import io.github.snowjug.sparta.data.repo.ScreeningRecorder
import io.github.snowjug.sparta.data.repo.ScreeningRepository
import io.github.snowjug.sparta.data.repo.ScreeningUploader
import io.github.snowjug.sparta.data.repo.SettingsFingerprinterSource
import io.github.snowjug.sparta.data.repo.SystemRepository
import io.github.snowjug.sparta.data.repo.UploadScheduler
import io.github.snowjug.sparta.platform.AndroidAnimatorScaleReader
import io.github.snowjug.sparta.platform.AndroidDeviceInfoProvider
import io.github.snowjug.sparta.platform.AndroidNotifier
import io.github.snowjug.sparta.platform.AndroidPermissionChecker
import io.github.snowjug.sparta.platform.AndroidRoleController
import io.github.snowjug.sparta.platform.AnimatorScaleReader
import io.github.snowjug.sparta.platform.ContentResolverContactsLookup
import io.github.snowjug.sparta.platform.DeviceInfoProvider
import io.github.snowjug.sparta.platform.PermissionChecker
import io.github.snowjug.sparta.platform.RoleController
import io.github.snowjug.sparta.work.WorkScheduler
import java.util.Calendar
import javax.inject.Qualifier
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient

@Qualifier
@Retention(AnnotationRetention.BINARY)
annotation class ApplicationScope

@Qualifier
@Retention(AnnotationRetention.BINARY)
annotation class IoDispatcher

/** Serves the owner-configured backend to OkHttp threads without blocking them on DataStore after start-up. */
class SettingsBaseUrlProvider(
    private val settings: SettingsRepository,
    scope: CoroutineScope,
) : BaseUrlProvider {
    @Volatile
    private var url: HttpUrl? = null

    @Volatile
    private var ready = false

    init {
        scope.launch(Dispatchers.IO) {
            settings.settings.map { it.backendUrl }.distinctUntilChanged().collect {
                url = it.toHttpUrlOrNull()
                ready = true
            }
        }
    }

    override fun current(): HttpUrl? {
        if (!ready) {
            // Only reachable in the first milliseconds after process start, and only from background threads.
            val value = runBlocking(Dispatchers.IO) { settings.current().backendUrl }
            url = value.toHttpUrlOrNull()
            ready = true
        }
        return url
    }
}

@Module
@InstallIn(SingletonComponent::class)
object AppModule {
    @Provides
    @Singleton
    @ApplicationScope
    fun applicationScope(): CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    @Provides
    @IoDispatcher
    fun ioDispatcher(): CoroutineDispatcher = Dispatchers.IO

    @Provides
    @Singleton
    fun wallClock(): WallClock = WallClock.System

    @Provides
    @Singleton
    fun idGenerator(): IdGenerator = IdGenerator.Random

    @Provides
    @Singleton
    fun monotonicClock(): MonotonicClock = MonotonicClock { SystemClock.elapsedRealtime() }

    @Provides
    @Singleton
    fun json(): Json = SpartaJson

    @Provides
    @Singleton
    fun backendUrlPolicy(): BackendUrlPolicy = BackendUrlPolicy(allowLocalCleartext = BuildConfig.ALLOW_LOCAL_CLEARTEXT)

    /** Minutes since local midnight, for quiet hours. */
    @Provides
    fun minuteOfDay(): MinuteOfDayProvider = MinuteOfDayProvider {
        val now = Calendar.getInstance()
        now.get(Calendar.HOUR_OF_DAY) * 60 + now.get(Calendar.MINUTE)
    }
}

@Module
@InstallIn(SingletonComponent::class)
object StorageModule {
    @Provides
    @Singleton
    fun database(@ApplicationContext context: Context): SpartaDatabase =
        Room.databaseBuilder(context, SpartaDatabase::class.java, SpartaDatabase.NAME).build()

    @Provides
    fun screeningEventDao(db: SpartaDatabase): ScreeningEventDao = db.screeningEvents()

    @Provides
    fun listEntryDao(db: SpartaDatabase): ListEntryDao = db.listEntries()

    @Provides
    fun cachedCallDao(db: SpartaDatabase): CachedCallDao = db.cachedCalls()

    @Provides
    fun notifiedItemDao(db: SpartaDatabase): NotifiedItemDao = db.notifiedItems()

    @Provides
    @Singleton
    fun dataStore(@ApplicationContext context: Context): DataStore<Preferences> = PreferenceDataStoreFactory.create(
        scope = CoroutineScope(SupervisorJob() + Dispatchers.IO),
        produceFile = { context.preferencesDataStoreFile("sparta_settings") },
    )

    @Provides
    @Singleton
    fun settingsRepository(store: DataStore<Preferences>): SettingsRepository = DataStoreSettingsRepository(store)
}

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {
    @Provides
    @Singleton
    fun baseUrlProvider(settings: SettingsRepository, @ApplicationScope scope: CoroutineScope): BaseUrlProvider =
        SettingsBaseUrlProvider(settings, scope)

    @Provides
    @Singleton
    fun authTokenProvider(): AuthTokenProvider = NoAuthTokenProvider

    @Provides
    @Singleton
    fun okHttpClient(baseUrl: BaseUrlProvider, tokens: AuthTokenProvider): OkHttpClient =
        NetworkFactory.createClient(baseUrl, tokens, userAgent = "SpartaAndroid/${BuildConfig.VERSION_NAME}")

    @Provides
    @Singleton
    fun spartaApi(client: OkHttpClient, json: Json): SpartaApi = NetworkFactory.createApi(client, json)

    @Provides
    @Singleton
    fun liveCallClient(api: SpartaApi, client: OkHttpClient, baseUrl: BaseUrlProvider, json: Json): LiveCallClient =
        LiveCallClient(api, client, baseUrl, json)

    @Provides
    fun liveEventSource(client: LiveCallClient): LiveEventSource = client

    @Provides
    @Singleton
    fun liveCallReducer(json: Json): LiveCallReducer = LiveCallReducer(json)

    @Provides
    fun liveCallSession(source: LiveEventSource, reducer: LiveCallReducer): LiveCallSession = LiveCallSession(source, reducer)

    @Provides
    @Singleton
    fun connectionTester(client: OkHttpClient, json: Json, policy: BackendUrlPolicy, clock: MonotonicClock): ConnectionTester =
        ConnectionTester(client, json, policy, clock)
}

@Module
@InstallIn(SingletonComponent::class)
object PlatformModule {
    @Provides
    @Singleton
    fun roleController(@ApplicationContext context: Context): RoleController = AndroidRoleController(context)

    @Provides
    @Singleton
    fun permissionChecker(@ApplicationContext context: Context): PermissionChecker = AndroidPermissionChecker(context)

    @Provides
    @Singleton
    fun deviceInfoProvider(): DeviceInfoProvider = AndroidDeviceInfoProvider()

    @Provides
    @Singleton
    fun animatorScaleReader(@ApplicationContext context: Context): AnimatorScaleReader = AndroidAnimatorScaleReader(context)

    @Provides
    @Singleton
    fun androidNotifier(@ApplicationContext context: Context): AndroidNotifier = AndroidNotifier(context)

    @Provides
    fun screeningNotifier(notifier: AndroidNotifier): ScreeningNotifier = notifier

    @Provides
    fun escalationNotifier(notifier: AndroidNotifier): EscalationNotifier = notifier

    @Provides
    @Singleton
    fun workScheduler(@ApplicationContext context: Context): WorkScheduler = WorkScheduler(WorkManager.getInstance(context))

    @Provides
    fun uploadScheduler(scheduler: WorkScheduler): UploadScheduler = scheduler
}

@Module
@InstallIn(SingletonComponent::class)
object RepositoryModule {
    @Provides
    @Singleton
    fun callsRepository(api: SpartaApi, dao: CachedCallDao, json: Json, clock: WallClock, ids: IdGenerator): CallsRepository =
        CallsRepository(api, dao, json, clock, ids)

    @Provides
    @Singleton
    fun screeningRepository(
        events: ScreeningEventDao,
        lists: ListEntryDao,
        api: SpartaApi,
        settings: SettingsRepository,
        clock: WallClock,
        json: Json,
    ): ScreeningRepository = ScreeningRepository(events, lists, api, settings, clock, json)

    @Provides
    @Singleton
    fun preferencesRepository(api: SpartaApi, settings: SettingsRepository, json: Json): PreferencesRepository =
        PreferencesRepository(api, settings, json)

    @Provides
    @Singleton
    fun systemRepository(api: SpartaApi, settings: SettingsRepository, json: Json, clock: WallClock): SystemRepository =
        SystemRepository(api, settings, json, clock)

    @Provides
    @Singleton
    fun screeningUploader(events: ScreeningEventDao, api: SpartaApi, json: Json): ScreeningUploader =
        ScreeningUploader(events, api, json)

    @Provides
    @Singleton
    fun screeningRecorder(
        events: ScreeningEventDao,
        settings: SettingsRepository,
        scheduler: UploadScheduler,
        notifier: ScreeningNotifier,
        ids: IdGenerator,
    ): ScreeningRecorder = ScreeningRecorder(events, settings, scheduler, notifier, ids)

    @Provides
    @Singleton
    fun escalationAnnouncer(
        notified: NotifiedItemDao,
        settings: SettingsRepository,
        preferences: PreferencesRepository,
        notifier: EscalationNotifier,
        clock: WallClock,
        minuteOfDay: MinuteOfDayProvider,
    ): EscalationAnnouncer = EscalationAnnouncer(notified, settings, preferences, notifier, clock, minuteOfDay)

    @Provides
    @Singleton
    fun backendConnector(
        tester: ConnectionTester,
        settings: SettingsRepository,
        screening: ScreeningRepository,
        system: SystemRepository,
    ): BackendConnector = BackendConnector(tester, settings, screening, system)

    @Provides
    @Singleton
    fun permissionModel(checker: PermissionChecker, settings: SettingsRepository): PermissionModel = PermissionModel(checker, settings)

    @Provides
    @Singleton
    fun escalationMonitor(
        source: LiveEventSource,
        announcer: EscalationAnnouncer,
        calls: CallsRepository,
        settings: SettingsRepository,
        json: Json,
    ): EscalationMonitor = EscalationMonitor(source, announcer, calls, settings, json)

    @Provides
    @Singleton
    fun backgroundSync(
        settings: SettingsRepository,
        screening: ScreeningRepository,
        preferences: PreferencesRepository,
        calls: CallsRepository,
        scheduler: UploadScheduler,
        announcer: EscalationAnnouncer,
        cachedCalls: CachedCallDao,
        notified: NotifiedItemDao,
        clock: WallClock,
    ): BackgroundSync = BackgroundSync(settings, screening, preferences, calls, scheduler, announcer, cachedCalls, notified, clock)
}

/** The screening fast path: local data only. */
@Module
@InstallIn(SingletonComponent::class)
object ScreeningModule {
    @Provides
    @Singleton
    fun localFactsGatherer(
        lists: ListEntryDao,
        permissions: PermissionChecker,
        @ApplicationContext appContext: Context,
        @IoDispatcher io: CoroutineDispatcher,
        settings: SettingsRepository,
    ): LocalFactsGatherer = LocalFactsGatherer(
        lists = RoomScreeningLists(lists),
        contacts = ContentResolverContactsLookup(appContext, permissions, io),
        fingerprinters = SettingsFingerprinterSource(settings),
        contactsEnabled = { settings.current().useContactsAsKnown },
    )

    @Provides
    @Singleton
    fun screeningCoordinator(
        @ApplicationScope scope: CoroutineScope,
        @IoDispatcher io: CoroutineDispatcher,
        clock: MonotonicClock,
        settings: SettingsRepository,
        gatherer: LocalFactsGatherer,
    ): ScreeningCoordinator = ScreeningCoordinator(
        scope = scope,
        workDispatcher = io,
        clock = clock,
        engine = ScreeningDecisionEngine(),
        loadPolicy = { settings.current().policy },
        gatherFacts = { request -> gatherer.gather(request) },
    )
}
