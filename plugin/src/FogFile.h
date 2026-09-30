#pragma once

namespace FoggyMap
{
	// An intensity bitmap written by the fog exporter: a "FOGM" header followed by raw 8-bit
	// rows. Deliberately trivial so the plugin needs no image decoding, and written
	// atomically on the other side so a half-written frame is never visible.
	struct FogImage
	{
		std::uint32_t             width{};
		std::uint32_t             height{};
		std::vector<std::uint8_t> pixels;  // width * height, top row first

		[[nodiscard]] bool Valid() const
		{
			return width > 0 && height > 0 &&
			       pixels.size() == static_cast<std::size_t>(width) * height;
		}
	};

	// Reads pipboy_<worldspace>.fog. Returns an invalid image if absent or malformed;
	// never throws.
	FogImage ReadFogFile(const std::filesystem::path& a_path);
}
