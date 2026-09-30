#include "PCH.h"

#include "Game.h"

namespace FoggyMap::Game
{
	const char* CurrentWorldspaceId()
	{
		auto* player = RE::PlayerCharacter::GetSingleton();
		if (!player) {
			return nullptr;
		}
		auto* cell = player->parentCell;
		if (!cell || !cell->worldSpace) {
			return nullptr;  // interior
		}
		const auto* editorId = cell->worldSpace->GetFormEditorID();
		return (editorId && *editorId) ? editorId : nullptr;
	}
}
