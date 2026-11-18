# R8 / ProGuard rules for the Sparta release build.
# Library consumer rules cover Retrofit, OkHttp, Room, Hilt/Dagger, WorkManager and kotlinx.serialization
# (the serialization compiler plugin generates serializers that R8 can see statically). The rules below only
# cover what we reference reflectively or by name.

# Keep line numbers for readable (sanitized) stack traces; hide the source file name.
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile

# Retrofit service interfaces are used through java.lang.reflect.Proxy.
-keep,allowobfuscation interface io.github.snowjug.sparta.data.remote.SpartaApi

# kotlinx.serialization: keep generated Companion.serializer() accessors of our DTO packages.
-keepclassmembers class io.github.snowjug.sparta.data.remote.dto.** {
    *** Companion;
}
-keepclasseswithmembers class io.github.snowjug.sparta.data.remote.dto.** {
    kotlinx.serialization.KSerializer serializer(...);
}
