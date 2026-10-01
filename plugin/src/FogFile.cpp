#include "PCH.h"

#include "FogFile.h"

#undef ERROR

namespace FoggyMap
{
	namespace
	{
		constexpr std::array<char, 4> kMagic{ 'F', 'O', 'G', 'M' };
		constexpr std::uint32_t       kVersion{ 1 };

		// Guards against a corrupt header asking us to allocate something absurd. The
		// real maps are 2048 square.
		constexpr std::uint32_t kMaxDimension{ 8192 };
	}

	FogImage ReadFogFile(const std::filesystem::path& a_path)
	{
		FogImage image;

		std::ifstream file{ a_path, std::ios::binary };
		if (!file) {
			return image;  // not exported yet; not an error
		}

		std::array<char, 4> magic{};
		std::uint32_t       version{};
		file.read(magic.data(), magic.size());
		file.read(reinterpret_cast<char*>(&version), sizeof(version));
		file.read(reinterpret_cast<char*>(&image.width), sizeof(image.width));
		file.read(reinterpret_cast<char*>(&image.height), sizeof(image.height));
		if (!file) {
			REX::WARN("fog file {} is truncated in its header", PathText(a_path));
			return {};
		}
		if (magic != kMagic || version != kVersion) {
			REX::WARN("fog file {} has an unexpected header", PathText(a_path));
			return {};
		}
		if (image.width > kMaxDimension || image.height > kMaxDimension) {
			REX::WARN("fog file {} claims an implausible size", PathText(a_path));
			return {};
		}

		const auto count = static_cast<std::size_t>(image.width) * image.height;
		image.pixels.resize(count);
		file.read(reinterpret_cast<char*>(image.pixels.data()), static_cast<std::streamsize>(count));
		if (static_cast<std::size_t>(file.gcount()) != count) {
			REX::WARN("fog file {} is truncated in its pixels", PathText(a_path));
			return {};
		}
		return image;
	}
}
