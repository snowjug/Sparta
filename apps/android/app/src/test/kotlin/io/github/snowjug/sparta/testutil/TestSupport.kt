package io.github.snowjug.sparta.testutil

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import io.github.snowjug.sparta.data.local.SpartaDatabase

object Fixtures {
    fun text(name: String): String {
        val stream = requireNotNull(Fixtures::class.java.classLoader?.getResourceAsStream("fixtures/$name")) { "missing fixture $name" }
        return stream.bufferedReader(Charsets.UTF_8).use { it.readText() }
    }
}

/** In-memory Room database (real SQL, real DAOs) for Robolectric tests. */
fun inMemoryDatabase(): SpartaDatabase {
    val context = ApplicationProvider.getApplicationContext<Context>()
    return Room.inMemoryDatabaseBuilder(context, SpartaDatabase::class.java)
        .allowMainThreadQueries()
        .build()
}
