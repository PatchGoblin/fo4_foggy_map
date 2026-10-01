#pragma once

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define NOSERVICE

#pragma warning(push)
#include "F4SE/F4SE.h"
#include "RE/Fallout.h"
#include "REX/REX.h"
#pragma warning(pop)

#define DLLEXPORT __declspec(dllexport)

#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <format>
#include <fstream>
#include <mutex>
#include <optional>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_set>
#include <vector>

using namespace std::literals;

namespace FoggyMap
{
	// A path as UTF-8, for logging. path::string() converts through the ANSI code page
	// and throws on any character it cannot represent -- a Cyrillic or CJK folder name
	// on a Western-locale system -- which would crash the game over a log line.
	inline std::string PathText(const std::filesystem::path& a_path)
	{
		std::string text;
		if (!REX::UTF16_TO_UTF8(a_path.native(), text)) {
			return "<unprintable path>";
		}
		return text;
	}
}
