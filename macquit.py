"""Make "Quit" from the Dock / app menu / logout work for the OpenCV window.

OpenCV's Cocoa window never installs a handler for the standard Apple Event
'aevt'/'quit', so macOS answers "can't quit" (-1708). This registers one with
NSAppleEventManager through the Objective-C runtime (ctypes, no PyObjC needed).
The handler only sets a flag; the main loop polls `requested()` and shuts down
cleanly (settings saved, Kinect released). Events are delivered while
cv2.waitKey() pumps the Cocoa event loop.
"""
import ctypes
import ctypes.util

_requested = False
_keep = []   # keep ctypes callbacks alive


def requested():
    return _requested


def install():
    global _requested
    try:
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Foundation.framework/Foundation")
    except OSError:
        return False
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.objc_allocateClassPair.restype = ctypes.c_void_p
    objc.objc_allocateClassPair.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
    objc.objc_registerClassPair.argtypes = [ctypes.c_void_p]
    objc.class_addMethod.restype = ctypes.c_bool
    objc.class_addMethod.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]

    def msg(restype, *argtypes):
        f = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)
        return f(ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value)

    IMP = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

    def on_quit(self, cmd, event, reply):
        global _requested
        _requested = True

    imp = IMP(on_quit)
    _keep.append(imp)
    name = b"KinectCamQuitHandler"
    cls = objc.objc_getClass(name)
    if not cls:
        cls = objc.objc_allocateClassPair(objc.objc_getClass(b"NSObject"), name, 0)
        sel = objc.sel_registerName(b"handleQuit:withReplyEvent:")
        objc.class_addMethod(cls, sel, ctypes.cast(imp, ctypes.c_void_p), b"v@:@@")
        objc.objc_registerClassPair(cls)
    send_id = msg(ctypes.c_void_p)
    obj = send_id(send_id(cls, objc.sel_registerName(b"alloc")), objc.sel_registerName(b"init"))
    _keep.append(obj)
    mgr = send_id(objc.objc_getClass(b"NSAppleEventManager"), objc.sel_registerName(b"sharedAppleEventManager"))
    set_handler = msg(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32)
    fourcc = lambda s: int.from_bytes(s, "big")  # noqa: E731
    set_handler(mgr, objc.sel_registerName(b"setEventHandler:andSelector:forEventClass:andEventID:"),
                obj, objc.sel_registerName(b"handleQuit:withReplyEvent:"), fourcc(b"aevt"), fourcc(b"quit"))
    return True
