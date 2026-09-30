#include "PCH.h"

#include "Config.h"
#include "FogFile.h"
#include "Game.h"
#include "PipboyOverlay.h"

#undef ERROR  // wingdi.h defines it, colliding with REX::ERROR

namespace FoggyMap::PipboyOverlay
{
	namespace
	{
		// Drawn once per opening of the Pip-Boy, not once per tick.
		bool g_drawn{ false };

		// The map's own coordinate space, from TextureHolder_mc's reported dimensions.
		constexpr double kMapExtent{ 2048.0 };

		constexpr auto kOverlayName{ "FoggyMapFog" };

		// Quantising the fog into levels lets neighbouring cells merge into single
		// rectangles. More levels means a softer edge but more rectangles.
		constexpr std::uint8_t kLevels{ 6 };

		// Never issue more than this many fills, however fragmented the fog. A runaway
		// loop here would stall the game while the Pip-Boy is open.
		constexpr std::size_t kMaxRectangles{ 6000 };

		// Cells across the map. Configurable because it trades how organic the fog edge
		// looks against how many fills it costs; must divide the fog image evenly.
		std::uint32_t Grid()
		{
			const auto configured = Config::Get().pipboyFogGrid;
			return (configured >= 16 && configured <= 512 && 2048 % configured == 0)
			           ? configured
			           : 128;
		}

		// Falls back to the Commonwealth only when the player is indoors, where there is
		// no world map to fog anyway.
		std::string WorldspaceForFog()
		{
			const auto* id = Game::CurrentWorldspaceId();
			return id ? std::string{ id } : std::string{ "Commonwealth" };
		}

		std::uint8_t LevelOf(std::uint8_t a_value)
		{
			return static_cast<std::uint8_t>((a_value * kLevels) / 256);
		}

		bool CallVoid(
			Scaleform::GFx::Value&       a_object,
			const char*                  a_method,
			const Scaleform::GFx::Value* a_args,
			std::uint32_t                a_count)
		{
			Scaleform::GFx::Value ignored;
			return a_object.Invoke(a_method, std::addressof(ignored), a_args, a_count);
		}

		// Averages the fog image down to one value per grid cell. Doing this here rather
		// than scaling inside Scaleform keeps the number of cross-boundary calls small.
		std::vector<std::uint8_t> Downsample(const FogImage& a_fog)
		{
			const auto                size = Grid();
			std::vector<std::uint8_t> grid(static_cast<std::size_t>(size) * size);
			const auto                blockX = a_fog.width / size;
			const auto                blockY = a_fog.height / size;
			if (blockX == 0 || blockY == 0) {
				return {};
			}

			for (std::uint32_t row = 0; row < size; ++row) {
				for (std::uint32_t column = 0; column < size; ++column) {
					std::uint32_t total = 0;
					for (std::uint32_t y = 0; y < blockY; ++y) {
						const auto source = (row * blockY + y) * a_fog.width + column * blockX;
						for (std::uint32_t x = 0; x < blockX; ++x) {
							total += a_fog.pixels[source + x];
						}
					}
					grid[row * size + column] =
						static_cast<std::uint8_t>(total / (blockX * blockY));
				}
			}
			return grid;
		}

		// Drops any layer we added previously, so reopening the Pip-Boy or refreshing the
		// fog does not stack layer upon layer.
		void RemoveExisting(Scaleform::GFx::Value& a_parent)
		{
			Scaleform::GFx::Value name[1];
			name[0] = kOverlayName;
			Scaleform::GFx::Value existing;
			if (a_parent.Invoke("getChildByName", std::addressof(existing), name, 1) &&
				existing.IsObject()) {
				Scaleform::GFx::Value child[1];
				child[0] = existing;
				Scaleform::GFx::Value ignored;
				a_parent.Invoke("removeChild", std::addressof(ignored), child, 1);
			}
		}

		// Draws the fog as filled rectangles on a Shape's Graphics. Runs of equal fog
		// level merge into one rectangle, which is what makes a fine grid affordable:
		// cost follows the length of the fog boundary, not the number of cells.
		bool DrawRectangles(
			Scaleform::GFx::Movie&           a_movie,
			Scaleform::GFx::Value&           a_textureHolder,
			const std::vector<std::uint8_t>& a_grid,
			std::vector<std::string>&        a_report)
		{
			RemoveExisting(a_textureHolder);

			Scaleform::GFx::Value shape;
			a_movie.CreateObject(std::addressof(shape), "flash.display.Shape", nullptr, 0);
			if (!shape.IsObject()) {
				a_report.emplace_back("could not create a Shape");
				return false;
			}
			Scaleform::GFx::Value graphics;
			if (!shape.GetMember("graphics", std::addressof(graphics)) || !graphics.IsObject()) {
				a_report.emplace_back("the Shape has no graphics object");
				return false;
			}

			const auto   grid = Grid();
			const double cell = kMapExtent / static_cast<double>(grid);
			const double strength = Config::Get().pipboyFogStrength;
			std::size_t  rectangles = 0;
			std::size_t  cells = 0;

			for (std::uint32_t row = 0; row < grid && rectangles < kMaxRectangles; ++row) {
				std::uint32_t column = 0;
				while (column < grid) {
					const auto level = LevelOf(a_grid[row * grid + column]);
					if (level == 0) {
						++column;
						continue;  // explored: leave the map untouched
					}
					std::uint32_t run = 1;
					while (column + run < grid &&
						   LevelOf(a_grid[row * grid + column + run]) == level) {
						++run;
					}

					Scaleform::GFx::Value fill[2];
					fill[0] = 0x4060A0;  // re-tinted by the Pip-Boy anyway
					// Mid-point of the level's band, so the faintest fog stays visible and
					// the densest reaches the configured strength.
					fill[1] = strength * ((level + 0.5) / kLevels);
					if (CallVoid(graphics, "beginFill", fill, 2)) {
						Scaleform::GFx::Value rect[4];
						rect[0] = column * cell;
						rect[1] = row * cell;
						rect[2] = run * cell;
						rect[3] = cell;
						CallVoid(graphics, "drawRect", rect, 4);
						CallVoid(graphics, "endFill", nullptr, 0);
						++rectangles;
						cells += run;
					}
					column += run;
				}
			}
			if (rectangles >= kMaxRectangles) {
				a_report.emplace_back("hit the rectangle cap; lower PipboyFogGrid");
			}
			a_report.emplace_back(std::format("drew {} cells as {} rectangles", cells, rectangles));
			if (rectangles == 0) {
				a_report.emplace_back("nothing fogged, or beginFill was refused");
				return cells == 0;  // a fully explored map is a success, not a failure
			}

			shape.SetMember("name", Scaleform::GFx::Value{ kOverlayName });
			Scaleform::GFx::Value child[1];
			child[0] = shape;
			if (!CallVoid(a_textureHolder, "addChild", child, 1)) {
				a_report.emplace_back("addChild refused the Shape");
				return false;
			}
			return true;
		}

		// The map's texture holder, or an unset value if the map page is not live. This is
		// the container whose coordinate space matches the exported fog.
		Scaleform::GFx::Value FindTextureHolder(RE::PipboyMenu& a_menu)
		{
			Scaleform::GFx::Value none;
			auto&                 mapPage = a_menu.mapMenuObj.mapPageObj;
			if (!mapPage.IsObject()) {
				return none;
			}
			Scaleform::GFx::Value holder;
			if (!mapPage.GetMember("WorldMapHolder_mc", std::addressof(holder)) ||
				!holder.IsObject()) {
				return none;
			}
			Scaleform::GFx::Value textureHolder;
			if (!holder.GetMember("TextureHolder_mc", std::addressof(textureHolder)) ||
				!textureHolder.IsObject()) {
				return none;
			}
			return textureHolder;
		}

		void WriteReport(const std::vector<std::string>& a_report)
		{
			const auto&     config = Config::Get();
			std::error_code error;
			std::filesystem::create_directories(config.outputDir, error);

			std::ofstream out{ config.outputDir / "pipboy_overlay.txt", std::ios::trunc };
			for (const auto& line : a_report) {
				if (out) {
					out << line << '\n';
				}
				REX::INFO("overlay: {}", line);
			}
		}
	}

	void Draw()
	{
		if (!Config::Get().pipboyOverlay) {
			return;
		}

		auto* ui = RE::UI::GetSingleton();
		if (!ui) {
			return;
		}
		const auto menu = ui->GetMenu<RE::PipboyMenu>();
		if (!menu) {
			g_drawn = false;  // Pip-Boy closed; draw again next time it opens
			return;
		}
		if (g_drawn) {
			return;
		}

		auto textureHolder = FindTextureHolder(*menu);
		if (!textureHolder.IsObject()) {
			return;  // the map page has not been shown yet
		}
		auto* movie = menu->uiMovie.get();
		if (!movie) {
			return;
		}

		// From here on, a failure is structural rather than a matter of timing, so it is
		// recorded and not retried every second.
		g_drawn = true;

		std::vector<std::string> report;
		const auto worldspace = WorldspaceForFog();
		const auto fog = ReadFogFile(
			Config::Get().outputDir / std::format("pipboy_{}.fog", worldspace));
		if (!fog.Valid()) {
			report.emplace_back(std::format("no usable fog file for {} yet", worldspace));
			WriteReport(report);
			return;
		}

		const auto grid = Downsample(fog);
		if (grid.empty()) {
			report.emplace_back("fog image is smaller than the overlay grid");
			WriteReport(report);
			return;
		}

		report.emplace_back(std::format("worldspace = {}", worldspace));
		DrawRectangles(*movie, textureHolder, grid, report);
		WriteReport(report);
	}
}
