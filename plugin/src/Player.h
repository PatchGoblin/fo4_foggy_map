#pragma once

namespace FoggyMap::Player
{
	// Writes player.json: the character, perks, inventory, quests, companion and load
	// order, as raw facts. The companion decides what is public and how it reads; this
	// only records. Rewritten at most every 30 seconds and only when something changed.
	// Main thread only.
	void Refresh();
}
