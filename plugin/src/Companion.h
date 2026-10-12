#pragma once

namespace FoggyMap
{
	// Starts the companion alongside the game. It runs in a kill-on-close job, so the
	// kernel ends it when the game process ends -- there is nothing to shut down.
	namespace Companion
	{
		// Launched minimised and without focus, so a fullscreen or ENB session is
		// never interrupted. Does nothing if disabled or already running.
		void Launch();

		// The folder our DLL was loaded from. Under MO2 this is the virtual
		// Data\F4SE\Plugins path, which MO2's VFS also resolves for child processes.
		std::filesystem::path PluginDirectory();
	}
}
