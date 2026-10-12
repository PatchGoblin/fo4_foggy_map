#include "PCH.h"

#include "Config.h"
#include "Companion.h"

#include <windows.h>

namespace FoggyMap::Companion
{
	namespace
	{
		HANDLE g_process{ nullptr };

		// A kill-on-close job that the companion lives in. Its handle is deliberately
		// never closed: the kernel closes it when the game process ends -- however it
		// ends, including crashes and TerminateProcess, where DllMain never runs -- and
		// that takes the companion down with it.
		HANDLE CompanionJob()
		{
			static const HANDLE job = [] {
				HANDLE created = CreateJobObjectW(nullptr, nullptr);
				if (!created) {
					REX::WARN("could not create the companion job (error {})", GetLastError());
					return HANDLE{ nullptr };
				}
				JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
				// Breakaway lets the companion start its exit publisher outside the job, so
				// that one process survives the game long enough to publish progress.
				limits.BasicLimitInformation.LimitFlags =
					JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK;
				if (!SetInformationJobObject(
						created, JobObjectExtendedLimitInformation, &limits, sizeof(limits))) {
					REX::WARN("could not configure the companion job (error {})", GetLastError());
					CloseHandle(created);
					return HANDLE{ nullptr };
				}
				return created;
			}();
			return job;
		}

		bool StillRunning()
		{
			if (!g_process) {
				return false;
			}
			return WaitForSingleObject(g_process, 0) == WAIT_TIMEOUT;
		}

		std::filesystem::path ModulePath(HMODULE a_module)
		{
			std::wstring buffer(32768, L'\0');
			const auto   length = GetModuleFileNameW(a_module, buffer.data(), static_cast<DWORD>(buffer.size()));
			buffer.resize(length);
			return buffer;
		}

		std::filesystem::path GameDataDirectory()
		{
			return ModulePath(nullptr).parent_path() / L"Data";
		}

		// Quoted for the command line. Inside quotes, backslashes before the closing quote
		// escape it, so "D:\Fog\" or "D:\" would swallow every later argument. Doubling
		// trailing backslashes is the standard rule: the child reads them back as written.
		std::wstring Quoted(const std::filesystem::path& a_path)
		{
			std::wstring text = a_path.wstring();
			std::size_t  trailing = 0;
			while (trailing < text.size() && text[text.size() - 1 - trailing] == L'\\') {
				++trailing;
			}
			text.append(trailing, L'\\');
			return L"\"" + text + L"\"";
		}
	}

	std::filesystem::path PluginDirectory()
	{
		HMODULE self{ nullptr };
		GetModuleHandleExW(
			GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
			reinterpret_cast<LPCWSTR>(&PluginDirectory), &self);
		return ModulePath(self).parent_path();
	}

	void Launch()
	{
		const auto& config = Config::Get();
		if (!config.autoLaunchCompanion) {
			return;
		}
		if (StillRunning()) {
			return;
		}

		// Capture the child's output. Launched with pythonw and no console, anything it
		// prints -- including the traceback from a crash -- would otherwise vanish, and a
		// companion that dies silently looks exactly like a companion that is idle.
		const auto logPath = config.outputDir / "companion.log";
		std::error_code error;
		std::filesystem::create_directories(config.outputDir, error);

		SECURITY_ATTRIBUTES inheritable{};
		inheritable.nLength = sizeof(inheritable);
		inheritable.bInheritHandle = TRUE;

		HANDLE log = CreateFileW(
			logPath.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
			std::addressof(inheritable), CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
		const bool haveLog = log != INVALID_HANDLE_VALUE;

		STARTUPINFOW startup{};
		startup.cb = sizeof(startup);
		startup.dwFlags = STARTF_USESHOWWINDOW;
		// Minimised and not activated: any window appears on the taskbar ready to
		// click, without stealing focus from the game.
		startup.wShowWindow = SW_SHOWMINNOACTIVE;
		if (haveLog) {
			startup.dwFlags |= STARTF_USESTDHANDLES;
			startup.hStdOutput = log;
			startup.hStdError = log;
		}

		PROCESS_INFORMATION process{};

		// The bundled companion sits beside this DLL; CompanionCommand overrides it, which
		// is how a developer runs it from a venv instead. Either way it is told where the
		// data and the game are, rather than guessing.
		std::wstring command = config.companionCommand;
		if (command.empty()) {
			const auto bundled = PluginDirectory() / L"FoggyMap" / L"FoggyMapCompanion.exe";
			if (!std::filesystem::exists(bundled, error)) {
				REX::WARN("companion not found at {}; the Pip-Boy fog will not update", PathText(bundled));
				return;
			}
			command = Quoted(bundled);
		}
		std::wstring commandLine = command + L" --data " + Quoted(config.outputDir) +
		                           L" --game-data " + Quoted(GameDataDirectory()) +
		                           L" --game-pid " + std::to_wstring(GetCurrentProcessId());
		REX::INFO("companion command: {}", PathText(commandLine));
		// CreateProcessW may modify the command line buffer, so the copy above is ours.
		commandLine.push_back(L'\0');

		// Handles must be inheritable for the child to write to the log.
		//
		// Started suspended so it is inside the job before it runs: the venv's pythonw
		// is a launcher that spawns the real interpreter, and a child spawned before
		// the assignment would escape the job and outlive the game.
		const BOOL inherit = haveLog ? TRUE : FALSE;
		const bool started = CreateProcessW(
			nullptr, commandLine.data(), nullptr, nullptr, inherit,
			CREATE_NO_WINDOW | CREATE_SUSPENDED, nullptr, nullptr, &startup, &process);
		if (haveLog) {
			CloseHandle(log);
		}
		if (!started) {
			REX::WARN("could not launch the companion (error {})", GetLastError());
			return;
		}

		const HANDLE job = CompanionJob();
		if (!job || !AssignProcessToJobObject(job, process.hProcess)) {
			// Still worth running: the fog works, it just outlives the game.
			REX::WARN("companion is not tied to the game (error {}); it will keep running after exit",
				GetLastError());
		}

		ResumeThread(process.hThread);
		CloseHandle(process.hThread);
		g_process = process.hProcess;
		REX::INFO("companion launched; its output goes to {}", PathText(logPath));
	}
}
