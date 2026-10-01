#pragma once

namespace FoggyMap
{
	// Everything the plugin reads from FoggyMap.ini. Defaults are usable as-is, so a
	// missing ini is not an error.
	struct Config
	{
		// Where the CSVs are written. Kept outside the game's Data folder so it never
		// lands in Mod Organizer's overwrite directory.
		std::filesystem::path outputDir;

		// How often the player's position is captured, in milliseconds.
		std::uint32_t sampleIntervalMs{ 1000 };

		// Skip a sample unless the player has moved at least this far since the last
		// one, so standing still does not bloat the file.
		float minMoveUnits{ 256.0F };

		// Record a sample regardless of movement after this long, so idle time is
		// still represented.
		std::uint32_t forceSampleSeconds{ 30 };

		// The companion keeps the in-game Pip-Boy fog current. Empty means the bundled
		// FoggyMap\FoggyMapCompanion.exe beside the DLL; set it to run another build, such
		// as a venv during development. The plugin appends --data and --game-data either way.
		std::wstring companionCommand;
		bool         autoLaunchCompanion{ true };

		// Draw the fog on the in-game Pip-Boy world map, as a vector layer attached to the
		// map's own texture holder so it inherits the map's pan and zoom.
		bool pipboyOverlay{ true };

		// How heavy the fog looks at its densest, 0 to 1. Purely a matter of taste, so it
		// lives here rather than being baked in.
		float pipboyFogStrength{ 0.85F };

		// Cells across the map. Higher follows the shape of the explored area more
		// closely and looks less like a grid; the cost is more rectangles, though far
		// less than proportionally because runs of equal fog merge into one.
		// Must divide the fog image (2048) evenly: 64, 128, 256.
		std::uint32_t pipboyFogGrid{ 256 };

		static Config& Get();

		// Reads Data/F4SE/Plugins/FoggyMap.ini if present. Never throws.
		void Load();
	};
}
