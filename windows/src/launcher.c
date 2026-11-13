/*
 * KinectCam.exe - starts KinectCam with the Python runtime bundled next to it.
 *
 * Layout (portable folder, nothing is installed):
 *   KinectCam.exe
 *   runtime\python\        Python 3.12 (embeddable) - python312._pth adds the folders below
 *   runtime\site-packages\ numpy, OpenCV, pyvirtualcam
 *   runtime\app\           KinectCam code + Kinect audio firmware
 *   runtime\lib\           libfreenect.dll, libusb-1.0.dll
 *   runtime\vcam\          Unity Capture virtual camera filter
 *   runtime\kinect_setup.exe   one-time driver/camera setup (asks for admin)
 *
 * Python runs inside this process (Py_Main from python312.dll), so the taskbar
 * shows KinectCam with its icon. Output goes to %LOCALAPPDATA%\KinectCam\KinectCam.log.
 *
 *   KinectCam.exe --restore-driver   gives the Kinect back to Windows' own drivers
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <shlobj.h>
#include <wchar.h>
#include <stdio.h>
#include <io.h>
#include <fcntl.h>

typedef int (*PY_MAIN)(int, wchar_t**);

/* Python builds os.environ from the C runtime's environment copy (shared ucrtbase),
   which SetEnvironmentVariableW alone does not update. */
static void setenv_both(const wchar_t* name, const wchar_t* value)
{
	SetEnvironmentVariableW(name, value);
	_wputenv_s(name, value);
}

/* Last lines of the log, for the error message box. */
static void tail_of(const wchar_t* path, wchar_t* out, size_t n)
{
	out[0] = 0;
	FILE* f = _wfopen(path, L"rb");
	if (!f) return;
	char buf[1600];
	fseek(f, 0, SEEK_END);
	long size = ftell(f);
	fseek(f, size > 1500 ? size - 1500 : 0, SEEK_SET);
	size_t got = fread(buf, 1, sizeof(buf) - 1, f);
	buf[got] = 0;
	fclose(f);
	MultiByteToWideChar(CP_UTF8, 0, buf, -1, out, (int)n);
}

static void fail(const wchar_t* msg)
{
	MessageBoxW(NULL, msg, L"KinectCam", MB_ICONERROR);
}

static int restore_driver(const wchar_t* runtime)
{
	wchar_t exe[MAX_PATH], params[MAX_PATH * 2];
	_snwprintf(exe, MAX_PATH, L"%ls\\kinect_setup.exe", runtime);
	_snwprintf(params, MAX_PATH * 2, L"--uninstall \"%ls\"", runtime);
	if (MessageBoxW(NULL, L"Give the Kinect back to Windows' own drivers and remove the KinectCam virtual camera?\n\n"
	                L"KinectCam will set them up again the next time you open it.",
	                L"KinectCam", MB_YESNO | MB_ICONQUESTION) != IDYES)
		return 0;
	SHELLEXECUTEINFOW info = { sizeof(info) };
	info.fMask = SEE_MASK_NOCLOSEPROCESS;
	info.lpVerb = L"runas";
	info.lpFile = exe;
	info.lpParameters = params;
	info.nShow = SW_HIDE;
	if (!ShellExecuteExW(&info)) return 1;
	WaitForSingleObject(info.hProcess, INFINITE);
	DWORD code = 1;
	GetExitCodeProcess(info.hProcess, &code);
	CloseHandle(info.hProcess);
	MessageBoxW(NULL, code == 0 ? L"Done. Unplug the Kinect and plug it back in."
	                            : L"Something could not be removed. See C:\\ProgramData\\KinectCam\\setup.log",
	            L"KinectCam", code == 0 ? MB_ICONINFORMATION : MB_ICONWARNING);
	return (int)code;
}

static void trace(const char* msg)
{
	/* plain Win32 output, independent of the C runtime: shows where a hard crash happens */
	DWORD w;
	HANDLE h = GetStdHandle(STD_ERROR_HANDLE);
	if (h && h != INVALID_HANDLE_VALUE) { WriteFile(h, msg, (DWORD)strlen(msg), &w, NULL); WriteFile(h, "\r\n", 2, &w, NULL); }
}

#ifdef KINECTCAM_CONSOLE
int wmain(void)
{
	return wWinMain(GetModuleHandleW(NULL), NULL, L"--debug --console", SW_SHOW);
}
#endif

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, LPWSTR cmdLine, int nShow)
{
	(void)hInst; (void)hPrev; (void)nShow;
	wchar_t root[MAX_PATH], runtime[MAX_PATH], buf[MAX_PATH], script[MAX_PATH], exe[MAX_PATH];
	GetModuleFileNameW(NULL, exe, MAX_PATH);
	wcscpy(root, exe);
	wchar_t* slash = wcsrchr(root, L'\\');
	if (slash) *slash = 0;
	_snwprintf(runtime, MAX_PATH, L"%ls\\runtime", root);

	if (cmdLine && wcsstr(cmdLine, L"--restore-driver"))
		return restore_driver(runtime);
	BOOL debug = cmdLine && wcsstr(cmdLine, L"--debug");

	/* environment for kinectcam.py */
	setenv_both(L"KINECTCAM_APP", L"1");
	setenv_both(L"KINECTCAM_RUNTIME", runtime);
	_snwprintf(buf, MAX_PATH, L"%ls\\lib", runtime);
	setenv_both(L"KINECTCAM_LIBDIR", buf);
	setenv_both(L"PYTHONDONTWRITEBYTECODE", L"1");
	setenv_both(L"PYTHONUTF8", L"1");

	wchar_t appdata[MAX_PATH], local[MAX_PATH], logdir[MAX_PATH], logfile[MAX_PATH];
	if (SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_APPDATA, NULL, 0, appdata))) {
		_snwprintf(buf, MAX_PATH, L"%ls\\KinectCam", appdata);
		CreateDirectoryW(buf, NULL);
		setenv_both(L"KINECTCAM_DATA", buf);
	}
	if (SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_LOCAL_APPDATA, NULL, 0, local))) {
		_snwprintf(logdir, MAX_PATH, L"%ls\\KinectCam", local);
		CreateDirectoryW(logdir, NULL);
		_snwprintf(logfile, MAX_PATH, L"%ls\\KinectCam.log", logdir);
		setenv_both(L"KINECTCAM_LOG", logfile);
		if (debug && wcsstr(cmdLine, L"--console")) {
			/* console build: stdout/stderr already go to this console */
		} else if (debug) {
			/* --debug: a console window shows everything live */
			AllocConsole();
			SetConsoleTitleW(L"KinectCam debug output");
			int cfd = _wopen(L"CONOUT$", _O_WRONLY | _O_BINARY);
			if (cfd >= 0) { _dup2(cfd, 1); _dup2(cfd, 2); }
			int ifd = _wopen(L"CONIN$", _O_RDONLY | _O_BINARY);
			if (ifd >= 0) _dup2(ifd, 0);
			SetStdHandle(STD_OUTPUT_HANDLE, (HANDLE)_get_osfhandle(1));
			SetStdHandle(STD_ERROR_HANDLE, (HANDLE)_get_osfhandle(2));
			SetStdHandle(STD_INPUT_HANDLE, (HANDLE)_get_osfhandle(0));
		} else {
			/* Python shares this C runtime (ucrtbase), so pointing file descriptors
			   1 and 2 at the log makes print() and tracebacks land there. */
			int fd = _wopen(logfile, _O_WRONLY | _O_CREAT | _O_TRUNC | _O_BINARY, _S_IREAD | _S_IWRITE);
			if (fd >= 0) {
				_dup2(fd, 1);
				_dup2(fd, 2);
				SetStdHandle(STD_OUTPUT_HANDLE, (HANDLE)_get_osfhandle(1));
				SetStdHandle(STD_ERROR_HANDLE, (HANDLE)_get_osfhandle(2));
			}
		}
	}

	trace("[launcher] KinectCam launcher started");
	/* load the bundled Python */
	_snwprintf(buf, MAX_PATH, L"%ls\\python\\python312.dll", runtime);
	HMODULE py = LoadLibraryExW(buf, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
	if (!py) {
		fail(L"KinectCam's files are incomplete (runtime\\python is missing).\n\n"
		     L"Unzip the whole KinectCam folder again and start KinectCam.exe from there.");
		return 1;
	}
	trace("[launcher] python312.dll loaded");
	PY_MAIN pyMain = (PY_MAIN)GetProcAddress(py, "Py_Main");
	if (!pyMain) { fail(L"Python runtime is damaged."); return 1; }

	_snwprintf(script, MAX_PATH, L"%ls\\app\\kinectcam.py", runtime);
	wchar_t* argv[] = { exe, L"-u", L"-X", L"faulthandler", script, NULL };
	trace("[launcher] starting Python");
	int rc = pyMain(5, argv);
	trace("[launcher] Python finished");
	fflush(NULL);
	if (debug) {
		char m[96];
		snprintf(m, sizeof(m), "\r\n[KinectCam exited with code %d - press Enter to close]", rc);
		trace(m);
		getchar();
	} else if (rc != 0 && rc != 3) {
		static wchar_t tail[1600], msg[2400];
		tail_of(logfile, tail, 1600);
		_snwprintf(msg, 2400, L"KinectCam stopped while starting (code %d).\n\nLast lines of %ls:\n\n%ls", rc, logfile, tail);
		fail(msg);
	}
	return rc;
}
