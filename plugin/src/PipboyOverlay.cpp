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
		// Drawn once per opening of the Pip-Boy, and again only if the companion writes a
		// newer fog file while it is still open: it may finish the export from just
		// before you opened it a second later.
		bool                                           g_drawn{ false };
		std::optional<std::filesystem::file_time_type> g_drawnStamp;

		// Diagnostics for the map art sometimes going missing behind the fog. Each
		// opening's report is kept, so good and bad openings can be compared.
		constexpr std::size_t                 kKeptOpenings{ 20 };
		constexpr int                         kFollowUpTicks{ 3 };
		bool                                  g_open{ false };
		std::uint32_t                         g_opening{ 0 };
		std::chrono::steady_clock::time_point g_openedAt{};
		int                                   g_followUps{ 0 };
		std::deque<std::vector<std::string>>  g_history;

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

		std::optional<std::filesystem::file_time_type> StampOf(const std::filesystem::path& a_path)
		{
			std::error_code error;
			const auto      stamp = std::filesystem::last_write_time(a_path, error);
			return error ? std::nullopt : std::optional{ stamp };
		}

		std::string Describe(const Scaleform::GFx::Value& a_value)
		{
			if (a_value.IsString()) {
				return a_value.GetString();
			}
			if (a_value.IsNumber()) {
				return std::format("{:.1f}", a_value.GetNumber());
			}
			if (a_value.IsInt()) {
				return std::to_string(a_value.GetInt());
			}
			if (a_value.IsUInt()) {
				return std::to_string(a_value.GetUInt());
			}
			if (a_value.IsBoolean()) {
				return a_value.GetBoolean() ? "true" : "false";
			}
			if (a_value.IsObject()) {
				return "object";
			}
			return a_value.IsUndefined() ? "undefined" : "?";
		}

		std::string MemberOf(Scaleform::GFx::Value& a_object, const char* a_name)
		{
			Scaleform::GFx::Value member;
			return a_object.GetMember(a_name, std::addressof(member)) ? Describe(member) : "-";
		}

		// What the texture holder contains, so a missing map image can be told apart from
		// one that is present but hidden, or one that arrives after the fog.
		void ListChildren(
			Scaleform::GFx::Value&    a_holder,
			std::string_view          a_label,
			std::vector<std::string>& a_report)
		{
			Scaleform::GFx::Value count;
			if (!a_holder.GetMember("numChildren", std::addressof(count))) {
				a_report.emplace_back(std::format("{}: numChildren unavailable", a_label));
				return;
			}
			// Scaleform reports numChildren as kInt, not kNumber.
			const auto children = count.IsInt()    ? count.GetInt() :
			                      count.IsNumber() ? static_cast<std::int32_t>(count.GetNumber()) :
			                                         -1;
			a_report.emplace_back(std::format("{}: {} children", a_label, children));

			for (std::int32_t index = 0; index < std::min(children, 32); ++index) {
				Scaleform::GFx::Value argument[1];
				argument[0] = index;
				Scaleform::GFx::Value child;
				if (!a_holder.Invoke("getChildAt", std::addressof(child), argument, 1) ||
					!child.IsObject()) {
					a_report.emplace_back(std::format("  [{}] unreadable", index));
					continue;
				}
				Scaleform::GFx::Value text;
				child.Invoke("toString", std::addressof(text), nullptr, 0);
				a_report.emplace_back(std::format(
					"  [{}] {} name={} size={}x{} visible={} alpha={}",
					index,
					Describe(text),
					MemberOf(child, "name"),
					MemberOf(child, "width"),
					MemberOf(child, "height"),
					MemberOf(child, "visible"),
					MemberOf(child, "alpha")));
			}
		}

		// Adds this tick's lines to the current opening and rewrites the report, which
		// holds the last few openings. Lines carry the time since the Pip-Boy opened.
		void WriteReport(const std::vector<std::string>& a_report)
		{
			if (g_history.empty()) {
				g_history.emplace_back();
			}
			const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
				std::chrono::steady_clock::now() - g_openedAt);
			for (const auto& line : a_report) {
				g_history.back().push_back(std::format("+{:>5} ms  {}", elapsed.count(), line));
				REX::INFO("overlay: {}", line);
			}

			const auto&     config = Config::Get();
			std::error_code error;
			std::filesystem::create_directories(config.outputDir, error);

			std::ofstream out{ config.outputDir / "pipboy_overlay.txt", std::ios::trunc };
			for (const auto& opening : g_history) {
				for (const auto& line : opening) {
					out << line << '\n';
				}
				out << '\n';
			}
		}

		void BeginOpening()
		{
			g_open = true;
			g_openedAt = std::chrono::steady_clock::now();
			g_history.emplace_back();
			while (g_history.size() > kKeptOpenings) {
				g_history.pop_front();
			}
			WriteReport({ std::format("=== opening {} ===", ++g_opening) });
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
			// Pip-Boy closed; draw again next time it opens
			g_open = false;
			g_drawn = false;
			g_followUps = 0;
			return;
		}
		if (!g_open) {
			BeginOpening();
		}

		auto textureHolder = FindTextureHolder(*menu);
		if (!textureHolder.IsObject()) {
			return;  // the map page has not been shown yet
		}
		auto* movie = menu->uiMovie.get();
		if (!movie) {
			return;
		}

		const auto worldspace = WorldspaceForFog();
		const auto fogPath = Config::Get().outputDir / std::format("pipboy_{}.fog", worldspace);
		const auto stamp = StampOf(fogPath);

		if (g_drawn && stamp == g_drawnStamp) {
			if (g_followUps > 0) {
				--g_followUps;
				std::vector<std::string> report;
				ListChildren(textureHolder, "later", report);
				WriteReport(report);
			}
			return;
		}

		// From here on, a failure is structural rather than a matter of timing, so it is
		// recorded and not retried until the fog file changes.
		g_drawn = true;
		g_drawnStamp = stamp;
		g_followUps = kFollowUpTicks;
		const auto started = std::chrono::steady_clock::now();

		std::vector<std::string> report;
		ListChildren(textureHolder, "before draw", report);
		const auto fog = ReadFogFile(fogPath);
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
		ListChildren(textureHolder, "after draw", report);
		report.emplace_back(std::format(
			"draw took {} ms",
			std::chrono::duration_cast<std::chrono::milliseconds>(
				std::chrono::steady_clock::now() - started)
				.count()));
		WriteReport(report);
	}
}
