#include "PCH.h"

#include "Config.h"
#include "Game.h"
#include "PipboyOverlay.h"
#include "Player.h"
#include "Recorder.h"
#include "Sampler.h"

namespace FoggyMap::Sampler
{
	namespace
	{
		std::atomic_bool g_running{ false };

		std::mutex         g_pendingLock;
		std::deque<Sample> g_pending;

		// Last recorded position, used for the minimum-movement filter. Only touched
		// on the main thread.
		bool  g_havePrevious{ false };
		float g_previousX{};
		float g_previousY{};
		std::chrono::steady_clock::time_point g_previousTime{};

		std::uint64_t NowMs()
		{
			using namespace std::chrono;
			return static_cast<std::uint64_t>(
				duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count());
		}

		// Runs on the main thread.
		void Capture()
		{
			const auto* worldspaceId = Game::CurrentWorldspaceId();
			if (!worldspaceId) {
				return;  // interior: the exterior door position is already covered
			}
			auto* player = RE::PlayerCharacter::GetSingleton();
			if (!player) {
				return;
			}

			const auto& config = Config::Get();
			const auto  location = player->data.location;
			const auto  now = std::chrono::steady_clock::now();

			if (g_havePrevious) {
				const auto deltaX = location.x - g_previousX;
				const auto deltaY = location.y - g_previousY;
				const auto movedFar =
					(deltaX * deltaX + deltaY * deltaY) >= (config.minMoveUnits * config.minMoveUnits);
				const auto waitedLong =
					std::chrono::duration_cast<std::chrono::seconds>(now - g_previousTime).count() >=
					config.forceSampleSeconds;
				if (!movedFar && !waitedLong) {
					return;
				}
			}

			g_havePrevious = true;
			g_previousX = location.x;
			g_previousY = location.y;
			g_previousTime = now;

			const std::scoped_lock lock{ g_pendingLock };
			g_pending.push_back(
				Sample{ std::string{ worldspaceId }, NowMs(), location.x, location.y, location.z });
		}

		// Discovering a location lifts the fog around its marker, but the discovered
		// flags only reached markers.csv on save load, so a new discovery stayed fogged
		// until the next load. Re-checking every few seconds gets it to the companion
		// well before the player opens the map. Runs on the main thread.
		constexpr std::chrono::seconds kMarkerRefreshInterval{ 5 };
		std::chrono::steady_clock::time_point g_lastMarkerRefresh{};

		void RefreshMarkers()
		{
			const auto now = std::chrono::steady_clock::now();
			if (now - g_lastMarkerRefresh < kMarkerRefreshInterval) {
				return;
			}
			g_lastMarkerRefresh = now;
			Recorder::WriteMarkers();
		}

		std::vector<Sample> DrainPending()
		{
			const std::scoped_lock lock{ g_pendingLock };
			std::vector<Sample>    drained{ g_pending.begin(), g_pending.end() };
			g_pending.clear();
			return drained;
		}

		void Run()
		{
			const auto interval = std::chrono::milliseconds{ Config::Get().sampleIntervalMs };
			const auto* tasks = F4SE::GetTaskInterface();

			while (g_running) {
				if (tasks) {
					// Both run on the main thread: reading the player's cell or the
					// menu tree off-thread could race with the game changing them.
					tasks->AddTask([]() {
						Capture();
						RefreshMarkers();
						Player::Refresh();
						PipboyOverlay::Draw();
					});
				}
				std::this_thread::sleep_for(interval);

				if (const auto drained = DrainPending(); !drained.empty()) {
					Recorder::AppendSamples(drained);
				}
			}

			// Do not lose whatever was captured just before shutdown.
			if (const auto drained = DrainPending(); !drained.empty()) {
				Recorder::AppendSamples(drained);
			}
		}
	}

	void Start()
	{
		if (g_running.exchange(true)) {
			return;  // already sampling; a save reload should not start a second thread
		}
		g_havePrevious = false;

		// Detached rather than joined: the only shutdown path is process exit, and
		// joining from DllMain could deadlock the loader.
		std::thread{ Run }.detach();
		REX::INFO("position sampling started");
	}

	void RequestStop()
	{
		g_running = false;
	}
}
