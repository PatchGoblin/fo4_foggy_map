#include "PCH.h"

#include "Companion.h"
#include "Config.h"
#include "Player.h"

namespace FoggyMap::Player
{
	namespace
	{
		constexpr std::chrono::seconds kRefreshInterval{ 30 };
		std::chrono::steady_clock::time_point g_lastRefresh{};

		// The last player.json written, so an unchanged snapshot is skipped.
		std::string g_lastWritten;

		// Quest flags (RE::QuestFlag) and the one objective state that matters here.
		constexpr std::uint16_t kQuestRecorded = 0x1 | 0x2 | 0x20 | 0x40;  // running, completed, shown, failed

		// Game strings hand out a null pointer when empty -- a quest with no editor ID,
		// an alias with no name -- and a string_view of null is strlen(null), which
		// crashed the game during the player probe.
		std::string_view Text(const char* a_text)
		{
			return a_text ? std::string_view{ a_text } : std::string_view{};
		}

		std::string_view Name(const RE::TESForm* a_form)
		{
			return a_form ? RE::TESFullName::GetFullName(*a_form) : std::string_view{};
		}

		// A JSON string literal. Game text is passed through as bytes; only quotes,
		// backslashes and control characters need escaping.
		std::string Json(std::string_view a_text)
		{
			std::string out;
			out.reserve(a_text.size() + 2);
			out += '"';
			for (const char c : a_text) {
				switch (c) {
				case '"':
					out += "\\\"";
					break;
				case '\\':
					out += "\\\\";
					break;
				case '\n':
					out += "\\n";
					break;
				case '\r':
					out += "\\r";
					break;
				case '\t':
					out += "\\t";
					break;
				default:
					if (static_cast<unsigned char>(c) < 0x20) {
						out += std::format("\\u{:04x}", static_cast<unsigned char>(c));
					} else {
						out += c;
					}
				}
			}
			out += '"';
			return out;
		}

		// Text with alias tokens such as <Alias=ActualLocation> filled in for one
		// instance of a quest, as the Pip-Boy shows it.
		std::string Parsed(std::string_view a_text, const RE::TESQuest* a_quest, std::uint32_t a_instance)
		{
			const std::string raw{ a_text };
			if (raw.empty() || !a_quest) {
				return raw;
			}
			RE::BSString text;
			text.Set(raw.data(), raw.size());
			RE::BGSQuestInstanceText::ParseString(&text, a_quest, a_instance);
			return std::string{ Text(text.c_str()) };
		}

		std::string ValuePair(RE::PlayerCharacter* a_player, RE::ActorValueInfo* a_info)
		{
			if (!a_info) {
				return "null";
			}
			return std::format("[{},{}]", a_player->GetBaseActorValue(*a_info), a_player->GetActorValue(*a_info));
		}

		std::string Character(RE::PlayerCharacter* a_player)
		{
			auto* values = RE::ActorValue::GetSingleton();
			std::string special = "{}";
			std::string stats = "{}";
			double      xp = 0;
			if (values) {
				special = std::format(
					R"({{"strength":{},"perception":{},"endurance":{},"charisma":{},"intelligence":{},"agility":{},"luck":{}}})",
					ValuePair(a_player, values->strength), ValuePair(a_player, values->perception),
					ValuePair(a_player, values->endurance), ValuePair(a_player, values->charisma),
					ValuePair(a_player, values->intelligence), ValuePair(a_player, values->agility),
					ValuePair(a_player, values->luck));
				stats = std::format(
					R"({{"health":{},"action_points":{},"rads":{},"carry_weight":{}}})",
					ValuePair(a_player, values->health), ValuePair(a_player, values->actionPoints),
					ValuePair(a_player, values->rads), ValuePair(a_player, values->carryWeight));
				if (values->experience) {
					xp = a_player->GetActorValue(*values->experience);
				}
			}
			return std::format(
				R"("character":{{"name":{},"sex":{},"level":{},"xp":{},"perk_points":{},"caps":{},"special":{},"stats":{}}})",
				Json(Text(a_player->GetDisplayFullName())), static_cast<int>(a_player->GetSex()),
				a_player->GetLevel(), xp, a_player->perkCount, a_player->GetGoldAmount(), special, stats);
		}

		std::string Time(RE::PlayerCharacter* a_player)
		{
			std::string game = "null";
			if (auto* calendar = RE::Calendar::GetSingleton()) {
				auto value = [](RE::TESGlobal* a_global) { return a_global ? a_global->GetValue() : 0.0f; };
				game = std::format(R"({{"year":{},"month":{},"day":{},"hour":{},"days_passed":{}}})",
					value(calendar->gameYear), value(calendar->gameMonth), value(calendar->gameDay),
					value(calendar->gameHour), value(calendar->gameDaysPassed));
			}
			// totalPlayingTime is milliseconds, confirmed against the in-game playtime.
			return std::format(R"("time":{{"playtime_ms":{},"game":{}}},"location":{})",
				static_cast<std::int64_t>(a_player->totalPlayingTime), game, Json(Name(a_player->currentLocation)));
		}

		// Each rank of a perk is its own form, chained through nextPerk, and reports
		// rank 1 when owned. Magazines are single forms with real ranks. Both are
		// recorded as they are; the companion rebuilds the chains.
		std::string Perks(RE::PlayerCharacter* a_player)
		{
			std::string out = R"("perks":[)";
			bool first = true;
			for (auto* perk : RE::TESDataHandler::GetSingleton()->GetFormArray<RE::BGSPerk>()) {
				if (!perk) {
					continue;
				}
				const auto rank = a_player->GetPerkRank(perk);
				if (rank == 0) {
					continue;
				}
				out += std::format(
					R"({}{{"id":{},"name":{},"rank":{},"ranks":{},"level":{},"playable":{},"hidden":{},"next":{}}})",
					first ? "" : ",", perk->formID, Json(Name(perk)), rank, perk->data.numRanks,
					perk->data.level, perk->data.playable, perk->data.hidden,
					perk->nextPerk ? perk->nextPerk->formID : 0);
				first = false;
			}
			return out + "]";
		}

		std::string Inventory(RE::PlayerCharacter* a_player)
		{
			std::string out = R"("inventory":[)";
			auto* list = a_player->inventoryList;
			if (!list) {
				return out + "]";
			}
			RE::BSAutoReadLock lock{ list->rwLock };
			bool first = true;
			for (auto& item : list->data) {
				if (!item.object) {
					continue;
				}
				std::uint32_t stackId = 0;
				for (auto* stack = item.stackData.get(); stack; stack = stack->nextStack.get(), ++stackId) {
					out += std::format(R"({}{{"id":{},"type":{},"name":{},"count":{},"equipped":{}}})",
						first ? "" : ",", item.object->formID, Json(Text(item.object->GetFormTypeString())),
						Json(Text(item.GetDisplayFullName(stackId))), stack->count, stack->IsEquipped());
					first = false;
				}
			}
			return out + "]";
		}

		// Quests the player has seen or that have run, without their objectives:
		// which objectives are showing comes from the player's own list below.
		std::string Quests()
		{
			std::string out = R"("quests":[)";
			bool first = true;
			for (auto* quest : RE::TESDataHandler::GetSingleton()->GetFormArray<RE::TESQuest>()) {
				if (!quest || (quest->data.flags & kQuestRecorded) == 0) {
					continue;
				}
				const auto name = Name(quest);
				if (name.empty()) {
					continue;
				}
				out += std::format(R"({}{{"id":{},"editor_id":{},"name":{},"flags":{},"type":{},"stage":{}}})",
					first ? "" : ",", quest->formID, Json(Text(quest->formEditorID.c_str())), Json(name),
					quest->data.flags, quest->data.questType, quest->currentStage);
				first = false;
			}
			return out + "]";
		}

		// The player's objective list is what the Pip-Boy shows, one entry per quest
		// instance -- radiant quests run several at once, each naming its own place.
		std::string Objectives(RE::PlayerCharacter* a_player)
		{
			std::string out = R"("objectives":[)";
			bool first = true;
			for (auto& entry : a_player->objectives) {
				auto* objective = entry.objective;
				auto* quest = objective ? objective->ownerQuest : nullptr;
				if (!quest) {
					continue;
				}
				out += std::format(R"({}{{"quest":{},"instance":{},"index":{},"state":{},"quest_name":{},"text":{}}})",
					first ? "" : ",", quest->formID, entry.instanceID, objective->index,
					static_cast<int>(entry.enstanceState.underlying()),
					Json(Parsed(Name(quest), quest, entry.instanceID)),
					Json(Parsed(Text(objective->displayText.c_str()), quest, entry.instanceID)));
				first = false;
			}
			return out + "]";
		}

		// Followers holds whoever is travelling with the player: a companion and Dogmeat
		// each have their own alias, and either can be empty.
		std::string Companions()
		{
			std::string out = R"("companions":[)";
			bool first = true;
			for (auto* quest : RE::TESDataHandler::GetSingleton()->GetFormArray<RE::TESQuest>()) {
				if (!quest || Text(quest->formEditorID.c_str()) != "Followers"sv) {
					continue;
				}
				for (auto* alias : quest->aliases) {
					if (!alias) {
						continue;
					}
					const auto aliasName = Text(alias->aliasName.c_str());
					if (aliasName != "Companion"sv && aliasName != "DogmeatCompanion"sv) {
						continue;
					}
					RE::ObjectRefHandle handle;
					quest->GetAliasedRef(&handle, alias->aliasID);
					const auto ref = handle.get();
					const auto name = ref ? Text(ref->GetDisplayFullName()) : std::string_view{};
					if (!name.empty()) {
						out += std::format("{}{}", first ? "" : ",", Json(name));
						first = false;
					}
				}
				break;
			}
			return out + "]";
		}

		std::string Mods()
		{
			std::string plugins = "[";
			bool first = true;
			auto* handler = RE::TESDataHandler::GetSingleton();
			for (auto* file : handler->compiledFileCollection.files) {
				plugins += std::format(R"({}{{"name":{},"index":{},"light":false}})", first ? "" : ",",
					Json(Text(file->filename)), file->compileIndex);
				first = false;
			}
			for (auto* file : handler->compiledFileCollection.smallFiles) {
				plugins += std::format(R"({}{{"name":{},"index":{},"light":true}})", first ? "" : ",",
					Json(Text(file->filename)), file->smallFileCompileIndex);
				first = false;
			}
			plugins += "]";

			std::string dlls = "[";
			first = true;
			std::error_code error;
			for (const auto& entry : std::filesystem::directory_iterator{ Companion::PluginDirectory(), error }) {
				if (entry.path().extension() == L".dll") {
					std::string name;
					if (REX::UTF16_TO_UTF8(entry.path().filename().native(), name)) {
						dlls += std::format("{}{}", first ? "" : ",", Json(name));
						first = false;
					}
				}
			}
			dlls += "]";
			return std::format(R"("mods":{{"plugins":{},"f4se":{}}})", plugins, dlls);
		}

		bool Write(const std::string& a_json)
		{
			const auto& dir = Config::Get().outputDir;
			std::error_code error;
			std::filesystem::create_directories(dir, error);
			const auto file = dir / "player.json";
			const auto temporary = dir / "player.json.tmp";
			{
				std::ofstream stream{ temporary, std::ios::trunc | std::ios::binary };
				if (!stream) {
					REX::ERROR("cannot open {}", PathText(temporary));
					return false;
				}
				stream << a_json;
			}
			// Swapped into place so the companion never reads a half-written file.
			std::filesystem::rename(temporary, file, error);
			if (error) {
				REX::ERROR("cannot replace {}: {}", PathText(file), error.message());
				return false;
			}
			return true;
		}
	}

	void Refresh()
	{
		const auto now = std::chrono::steady_clock::now();
		if (now - g_lastRefresh < kRefreshInterval) {
			return;
		}
		auto* player = RE::PlayerCharacter::GetSingleton();
		if (!player || !player->parentCell || !RE::TESDataHandler::GetSingleton()) {
			return;  // no game loaded yet
		}
		g_lastRefresh = now;

		const auto started = std::chrono::steady_clock::now();
		const auto json = std::format("{{\"version\":1,{},{},{},{},{},{},{},{}}}\n",
			Character(player), Time(player), Perks(player), Inventory(player), Quests(),
			Objectives(player), Companions(), Mods());

		// Paused in a menu, nothing moves -- not even the game clock -- so skip the write.
		if (json == g_lastWritten) {
			return;
		}
		if (Write(json)) {
			g_lastWritten = json;
			const auto elapsed = std::chrono::duration_cast<std::chrono::microseconds>(
				std::chrono::steady_clock::now() - started);
			REX::INFO("wrote player.json ({} bytes) in {} us", json.size(), elapsed.count());
		}
	}
}
