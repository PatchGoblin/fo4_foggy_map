#include "PCH.h"

#include "Config.h"
#include "Recorder.h"

namespace FoggyMap::Recorder
{
	namespace
	{
		std::mutex g_writeLock;

		// MapMarkerData's members are private in CommonLibF4, so they are read by
		// offset instead. Layout from RE/M/MapMarkerData.h: TESFullName base occupies
		// 0x00-0x0F, then flags 0x10, originalFlags 0x11, type 0x12.
		static_assert(sizeof(RE::MapMarkerData) == 0x18);
		constexpr std::size_t kFlagsOffset{ 0x10 };
		constexpr std::size_t kTypeOffset{ 0x12 };

		// Bit 0 of the marker flags is "visible on the map", i.e. discovered. Verify
		// against the Pip-Boy for a few known locations before trusting it: this is
		// the one value here that is inferred rather than declared by the headers.
		constexpr std::uint8_t kVisibleFlag{ 1 << 0 };

		std::uint8_t ByteAt(const RE::MapMarkerData* a_data, std::size_t a_offset)
		{
			return *(reinterpret_cast<const std::uint8_t*>(a_data) + a_offset);
		}

		// Commas and quotes in a location name would otherwise break the CSV.
		std::string Quote(std::string_view a_text)
		{
			std::string out;
			out.reserve(a_text.size() + 2);
			out.push_back('"');
			for (const auto character : a_text) {
				if (character == '"') {
					out.push_back('"');
				}
				out.push_back(character);
			}
			out.push_back('"');
			return out;
		}

		bool EnsureOutputDir(const std::filesystem::path& a_dir)
		{
			std::error_code error;
			std::filesystem::create_directories(a_dir, error);
			if (error) {
				REX::ERROR("cannot create {}: {}", PathText(a_dir), error.message());
				return false;
			}
			return true;
		}

		std::string_view EditorId(const RE::TESForm* a_form)
		{
			const auto* id = a_form ? a_form->GetFormEditorID() : nullptr;
			return id ? std::string_view{ id } : std::string_view{};
		}

		// Collects every map marker reference in a worldspace. Markers live in the
		// worldspace's persistent cell, and some are reached through the fixed
		// persistent reference map, so both are walked and results deduplicated.
		void CollectMarkers(
			RE::TESWorldSpace*                     a_worldspace,
			std::vector<RE::TESObjectREFR*>&       a_out,
			std::unordered_set<std::uint32_t>&     a_seen)
		{
			const auto consider = [&](RE::TESObjectREFR* a_ref) {
				if (!a_ref || !a_ref->extraList) {
					return;
				}
				if (!a_ref->extraList->HasType<RE::ExtraMapMarker>()) {
					return;
				}
				if (a_seen.insert(a_ref->formID).second) {
					a_out.push_back(a_ref);
				}
			};

			if (auto* cell = a_worldspace->persistentCell) {
				for (const auto& ref : cell->references) {
					consider(ref.get());
				}
			}
			for (const auto& entry : a_worldspace->fixedPersistentRefMap) {
				if (entry.second) {
					for (const auto& ref : *entry.second) {
						consider(ref.get());
					}
				}
			}
		}
	}

	void AppendSamples(const std::vector<Sample>& a_samples)
	{
		if (a_samples.empty()) {
			return;
		}

		const auto& config = Config::Get();
		if (!EnsureOutputDir(config.outputDir)) {
			return;
		}

		const std::scoped_lock lock{ g_writeLock };

		// Group by worldspace so each file is opened once per flush.
		for (std::size_t index = 0; index < a_samples.size();) {
			const auto& worldspace = a_samples[index].worldspace;
			const auto  file = config.outputDir / std::format("path_{}.csv", worldspace);

			const bool isNew = !std::filesystem::exists(file);
			std::ofstream out{ file, std::ios::app };
			if (!out) {
				REX::ERROR("cannot open {}", PathText(file));
				return;
			}
			if (isNew) {
				out << "t_ms,x,y,z\n";
			}

			for (; index < a_samples.size() && a_samples[index].worldspace == worldspace; ++index) {
				const auto& sample = a_samples[index];
				out << std::format(
					"{},{:.2f},{:.2f},{:.2f}\n", sample.timeMs, sample.x, sample.y, sample.z);
			}
			// Flushed on close: the companion polls the file while the game runs.
		}
	}

	void WriteMarkers()
	{
		auto* handler = RE::TESDataHandler::GetSingleton();
		if (!handler) {
			REX::WARN("no data handler, skipping marker dump");
			return;
		}

		const auto& config = Config::Get();
		if (!EnsureOutputDir(config.outputDir)) {
			return;
		}

		const auto file = config.outputDir / "markers.csv";
		const auto temporary = config.outputDir / "markers.csv.tmp";

		std::ofstream out{ temporary, std::ios::trunc };
		if (!out) {
			REX::ERROR("cannot open {}", PathText(temporary));
			return;
		}
		out << "worldspace,form_id,name,x,y,radius,marker_type,discovered\n";

		std::size_t total = 0;
		std::size_t discovered = 0;

		for (auto* worldspace : handler->GetFormArray<RE::TESWorldSpace>()) {
			if (!worldspace) {
				continue;
			}
			const auto worldspaceId = EditorId(worldspace);
			if (worldspaceId.empty()) {
				continue;
			}

			std::vector<RE::TESObjectREFR*>   markers;
			std::unordered_set<std::uint32_t> seen;
			CollectMarkers(worldspace, markers, seen);

			for (auto* marker : markers) {
				const auto* extra = marker->extraList->GetByType<RE::ExtraMapMarker>();
				if (!extra || !extra->mapMarkerData) {
					continue;
				}
				const auto* data = extra->mapMarkerData;

				const auto flags = ByteAt(data, kFlagsOffset);
				const bool isDiscovered = (flags & kVisibleFlag) != 0;

				std::string_view name;
				if (const auto* full = static_cast<const RE::TESFullName*>(data)->GetFullName()) {
					name = full;
				}

				out << std::format(
					"{},0x{:08X},{},{:.2f},{:.2f},,{},{}\n",
					worldspaceId,
					marker->formID,
					Quote(name),
					marker->data.location.x,
					marker->data.location.y,
					ByteAt(data, kTypeOffset),
					isDiscovered ? 1 : 0);

				++total;
				discovered += isDiscovered ? 1 : 0;
			}
		}
		out.close();

		// Swap into place so the companion never reads a half-written file.
		std::error_code error;
		std::filesystem::rename(temporary, file, error);
		if (error) {
			REX::ERROR("cannot replace {}: {}", PathText(file), error.message());
			return;
		}

		REX::INFO("wrote {} map markers ({} discovered)", total, discovered);
	}
}
