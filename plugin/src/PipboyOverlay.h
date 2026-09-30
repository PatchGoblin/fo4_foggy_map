#pragma once

namespace FoggyMap
{
	// Draws the exploration fog on the in-game Pip-Boy world map.
	//
	// The fog is a vector layer parented to the map page's own TextureHolder_mc, whose
	// coordinate space is exactly the 2048-unit map image -- the same space the fog is
	// exported in. So the layer inherits FallUI's pan and zoom with no coordinate maths,
	// the map art is never modified, and markers keep drawing on top because they live
	// in a sibling holder.
	//
	// Three other routes were tried and are recorded here so they are not retried:
	//
	//   * Replacing the map's ID3D11 pointers. The writes landed and persisted, and the
	//     menu re-sent its textures, but nothing changed on screen: Scaleform builds its
	//     own image once and never re-reads that struct.
	//   * WorldMapHolder_mc.SetTexture. Callable, but refuses every argument shape.
	//   * Per-pixel BitmapData writes. setPixel32 and setPixel are both refused by this
	//     Scaleform build, on a bitmap that reports its dimensions correctly. Hence
	//     rectangles rather than pixels.
	namespace PipboyOverlay
	{
		// Redraws the fog layer if the Pip-Boy map is open and it has not been drawn for
		// this opening yet. Cheap when there is nothing to do. Main thread only.
		void Draw();
	}
}
