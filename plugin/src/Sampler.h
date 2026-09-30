#pragma once

namespace FoggyMap
{
	// Records where the player goes.
	//
	// A background thread only keeps time. The actual read of game state is posted to
	// the main thread through F4SE's task interface, because touching the player's
	// cell pointer from another thread could race with a cell change. File writes
	// happen back on the background thread so the game never waits on disk.
	namespace Sampler
	{
		void Start();

		// Signals the sampling thread to finish without waiting for it. Safe to call
		// from DllMain, where waiting on a thread could deadlock the loader.
		void RequestStop();
	}
}
