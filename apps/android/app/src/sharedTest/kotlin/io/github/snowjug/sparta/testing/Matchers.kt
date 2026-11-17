package io.github.snowjug.sparta.testing

import androidx.compose.ui.test.SemanticsNodeInteraction
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.hasAnyDescendant
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.ComposeContentTestRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performClick as libraryPerformClick

/**
 * Taps a node, scrolling it into view first when it sits in a scrollable list (long screens do not fit a phone window).
 * Nodes outside a scrollable container (dialogs, bars) are tapped where they are.
 */
fun SemanticsNodeInteraction.performClick(): SemanticsNodeInteraction {
    runCatching { performScrollTo() }
    return libraryPerformClick()
}

/**
 * Like the library's `assertTextContains`, but it also accepts a container (a card, a banner) whose descendants hold
 * the text: those nodes do not merge their children's text into their own semantics.
 */
fun SemanticsNodeInteraction.assertTextContains(text: String, substring: Boolean = false): SemanticsNodeInteraction =
    assert(hasText(text, substring = substring) or hasAnyDescendant(hasText(text, substring = substring)))

/** Asserts that [text] is shown nowhere inside the node tagged [tag]. */
fun ComposeContentTestRule.assertNoTextInside(tag: String, text: String) {
    onNodeWithTag(tag).assert(!(hasText(text, substring = true) or hasAnyDescendant(hasText(text, substring = true))))
}
