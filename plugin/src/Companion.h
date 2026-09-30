#pragma once

namespace FoggyMap
{
	// Starts the companion window alongside the game and closes it again afterwards,
	// so there is nothing to launch or remember to shut down.
	namespace Companion
	{
		// Launched minimised and without focus, so a fullscreen or ENB session is
		// never interrupted. Does nothing if disabled or already running.
		void Launch();

		void Terminate();
	}
}
