#include "PCH.h"

#include "Config.h"
#include "PipboyOverlay.h"
#include "Recorder.h"
#include "Sampler.h"
#include "Companion.h"

#include <windows.h>

// wingdi.h defines ERROR as a macro, which collides with REX::ERROR.
#undef ERROR

namespace
{
	constexpr auto kPluginName = "FoggyMap"sv;
	constexpr std::uint32_t kVersionMajor{ 0 };
	constexpr std::uint32_t kVersionMinor{ 1 };
	constexpr std::uint32_t kVersionPatch{ 0 };

	void MessageHandler(F4SE::MessagingInterface::Message* a_message)
	{
		if (!a_message) {
			return;
		}

		switch (a_message->type) {
		case F4SE::MessagingInterface::kGameLoaded:
			FoggyMap::Companion::Launch();
			break;

		// Both a loaded save and a new game are points where the marker snapshot
		// needs refreshing: discovered state belongs to the save, not the session.
		case F4SE::MessagingInterface::kPostLoadGame:
		case F4SE::MessagingInterface::kNewGame:
			FoggyMap::Recorder::WriteMarkers();
			FoggyMap::Sampler::Start();
			break;

		default:
			break;
		}
	}
}

// OG F4SE (0.6.23) consumes F4SEPlugin_Query and ignores PluginVersionData, while
// NG/AE consume F4SEPlugin_Version and ignore Query. Exporting both lets one DLL
// load on any of them; Address Library resolves the per-runtime addresses.
extern "C" DLLEXPORT bool F4SEAPI F4SEPlugin_Query(
	const F4SE::QueryInterface* a_f4se, F4SE::PluginInfo* a_info)
{
	if (!a_f4se || !a_info) {
		return false;
	}
	if (a_f4se->RuntimeVersion() != F4SE::RUNTIME_1_10_163) {
		return false;  // newer runtimes go through F4SEPlugin_Version
	}
	a_info->infoVersion = F4SE::PluginInfo::kVersion;
	a_info->name = kPluginName.data();
	a_info->version = kVersionMajor;
	return true;
}

extern "C" DLLEXPORT constinit auto F4SEPlugin_Version = []() noexcept {
	F4SE::PluginVersionData data{};

	data.PluginVersion({ kVersionMajor, kVersionMinor, kVersionPatch, 0 });
	data.PluginName(kPluginName.data());
	data.AuthorName("FoggyMap");
	data.UsesSigScanning(false);
	data.HasNoStructUse(false);
	data.UsesAddressLibrary(true);
	data.IsLayoutDependent(true);
	// commonlibf4's helpers set only the AE bit; advertise NG support as well.
	data.addressIndependence |= (1u << 1);
	data.structureIndependence |= (1u << 1);
	data.CompatibleVersions({});

	return data;
}();

extern "C" DLLEXPORT bool F4SEAPI F4SEPlugin_Load(const F4SE::LoadInterface* a_f4se)
{
	F4SE::Init(a_f4se);

	REX::INFO("FoggyMap v{}.{}.{}", kVersionMajor, kVersionMinor, kVersionPatch);
	REX::INFO("runtime: {}", a_f4se->RuntimeVersion().string());

	FoggyMap::Config::Get().Load();

	const auto* messaging = F4SE::GetMessagingInterface();
	if (!messaging || !messaging->RegisterListener(MessageHandler)) {
		REX::ERROR("could not register message listener");
		return false;
	}

	return true;
}

// The game is going away: take the companion with us so there is nothing left running.
//
// Only signalling and a TerminateProcess call happen here. Waiting on our own thread
// would risk a loader-lock deadlock, and by the time DLL_PROCESS_DETACH runs on
// process exit Windows has already stopped the other threads anyway. At worst the
// last second of movement goes unwritten.
BOOL APIENTRY DllMain(HMODULE, DWORD a_reason, LPVOID)
{
	if (a_reason == DLL_PROCESS_DETACH) {
		FoggyMap::Sampler::RequestStop();
		FoggyMap::Companion::Terminate();
	}
	return TRUE;
}
