#pragma once

namespace FoggyMap
{
	// One captured player position, in raw Fallout 4 world units.
	struct Sample
	{
		std::string   worldspace;
		std::uint64_t timeMs{};
		float         x{};
		float         y{};
		float         z{};
	};

	// Writes the two files the companion reads: an append-only position log per
	// worldspace, and a snapshot of every map marker with its discovered state.
	namespace Recorder
	{
		// Appends samples to path_<worldspace>.csv, creating files and headers as
		// needed. Safe to call from any thread; does its own locking.
		void AppendSamples(const std::vector<Sample>& a_samples);

		// Rewrites markers.csv from the live game state, so mod-added markers and
		// discovered flags are all included. Must run on the main thread.
		void WriteMarkers();
	}
}
