#include "PCH.h"

#include "Config.h"

#include <windows.h>

namespace FoggyMap
{
	namespace
	{
		constexpr auto kIniPath = "Data/F4SE/Plugins/FoggyMap.ini"sv;

		std::string_view Trim(std::string_view a_text)
		{
			const auto first = a_text.find_first_not_of(" \t\r\n"sv);
			if (first == std::string_view::npos) {
				return {};
			}
			const auto last = a_text.find_last_not_of(" \t\r\n"sv);
			return a_text.substr(first, last - first + 1);
		}

		std::filesystem::path DefaultOutputDir()
		{
			std::wstring buffer(MAX_PATH, L'\0');
			const auto   length =
				GetEnvironmentVariableW(L"LOCALAPPDATA", buffer.data(), static_cast<DWORD>(buffer.size()));
			if (length > 0 && length < buffer.size()) {
				buffer.resize(length);
				return std::filesystem::path{ buffer } / L"FoggyMap";
			}
			// Falls back to a folder beside the game executable.
			return std::filesystem::path{ "FoggyMap" };
		}

		bool AsBool(std::string_view a_value)
		{
			return a_value == "1"sv || a_value == "true"sv || a_value == "True"sv;
		}
	}

	Config& Config::Get()
	{
		static Config instance;
		return instance;
	}

	void Config::Load()
	{
		outputDir = DefaultOutputDir();

		std::ifstream file{ std::filesystem::path{ kIniPath } };
		if (!file) {
			REX::INFO("no FoggyMap.ini found, using defaults");
			return;
		}

		std::string line;
		while (std::getline(file, line)) {
			const auto trimmed = Trim(line);
			if (trimmed.empty() || trimmed.front() == ';' || trimmed.front() == '#' ||
				trimmed.front() == '[') {
				continue;
			}

			const auto split = trimmed.find('=');
			if (split == std::string_view::npos) {
				continue;
			}
			const auto key = Trim(trimmed.substr(0, split));
			const auto value = Trim(trimmed.substr(split + 1));

			try {
				if (key == "OutputDir"sv && !value.empty()) {
					outputDir = std::filesystem::path{ std::string{ value } };
				} else if (key == "SampleIntervalMs"sv) {
					sampleIntervalMs = static_cast<std::uint32_t>(std::stoul(std::string{ value }));
				} else if (key == "MinMoveUnits"sv) {
					minMoveUnits = std::stof(std::string{ value });
				} else if (key == "ForceSampleSeconds"sv) {
					forceSampleSeconds = static_cast<std::uint32_t>(std::stoul(std::string{ value }));
				} else if (key == "CompanionCommand"sv) {
					companionCommand = std::filesystem::path{ std::string{ value } }.wstring();
				} else if (key == "AutoLaunchCompanion"sv) {
					autoLaunchCompanion = AsBool(value);
				} else if (key == "PipboyOverlay"sv) {
					pipboyOverlay = AsBool(value);
				} else if (key == "PipboyFogStrength"sv) {
					pipboyFogStrength = std::clamp(std::stof(std::string{ value }), 0.0F, 1.0F);
				} else if (key == "PipboyFogGrid"sv) {
					pipboyFogGrid = static_cast<std::uint32_t>(std::stoul(std::string{ value }));
				}
			} catch (const std::exception&) {
				REX::WARN("ignoring malformed FoggyMap.ini value for {}", key);
			}
		}

		// A sub-second interval would add cost for no benefit: the fog radius is tens
		// of metres, far more than the player covers in a second.
		sampleIntervalMs = std::max<std::uint32_t>(sampleIntervalMs, 250);

		REX::INFO("output dir: {}", outputDir.string());
		REX::INFO("sample interval: {} ms, min move: {} units", sampleIntervalMs, minMoveUnits);
	}
}
