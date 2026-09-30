#pragma once

namespace FoggyMap::Game
{
	// Editor ID of the exterior worldspace the player is currently in, or nullptr when
	// they are indoors or the world is not loaded yet.
	//
	// Must be called on the main thread: it walks the player's cell pointer, which the
	// game rewrites on every cell change.
	const char* CurrentWorldspaceId();
}
