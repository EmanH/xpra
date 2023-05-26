# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

import json

from xpra.platform.keyboard_base import KeyboardBase
from xpra.dbus.helper import DBusHelper, native_to_dbus, dbus_to_native
from xpra.keyboard.mask import MODIFIER_MAP
from xpra.log import Logger
from xpra.os_util import is_X11, is_Wayland, bytestostr
if is_X11():
    from xpra.gtk_common.error import xsync

log = Logger("keyboard", "posix")


class Keyboard(KeyboardBase):

    def __init__(self):
        super().__init__()
        if is_X11():
            try:
                #pylint: disable=import-outside-toplevel
                from xpra.x11.bindings.keyboard import X11KeyboardBindings   #@UnresolvedImport
                self.keyboard_bindings = X11KeyboardBindings()
            except Exception as e:
                log("keyboard bindings", exc_info=True)
                from xpra.gtk_common.gtk_util import ds_inited
                if not ds_inited():
                    log.error("Error: failed to load the X11 keyboard bindings")
                    log.error(" %s", str(e) or type(e))
                    log.error(" keyboard mapping may be incomplete")

    def init_vars(self):
        super().init_vars()
        self.keymap_modifiers = None
        self.keyboard_bindings = None
        self.__dbus_helper = DBusHelper()
        self.__input_sources = {}
        self._dbus_gnome_shell_eval_ism(
            ".inputSources",
            self._store_input_sources,
        )

    def _store_input_sources(self, input_sources):
        log("_store_input_sources(%s)", input_sources)
        for layout_info in input_sources.values():
            index = int(layout_info["index"])
            layout_variant = str(layout_info["id"])
            layout = layout_variant.split("+", 1)[0]
            self.__input_sources[layout] = index

    def _dbus_gnome_shell_eval_ism(self, cmd, callback=None):
        ism = "imports.ui.status.keyboard.getInputSourceManager()"

        def ok_cb(success, res):
            try:
                if not dbus_to_native(success):
                    log("_dbus_gnome_shell_eval_ism(%s): %s", cmd, msg)
                    return
                if callback is not None:
                    callback(json.loads(dbus_to_native(res)))
            except Exception:
                log("_dbus_gnome_shell_eval_ism(%s)", cmd, exc_info=True)

        def err_cb(msg):
            log("_dbus_gnome_shell_eval_ism(%s): %s", cmd, msg)

        self.__dbus_helper.call_function(
            "org.gnome.Shell",
            "/org/gnome/Shell",
            "org.gnome.Shell",
            "Eval",
            [native_to_dbus(ism + cmd)],
            ok_cb,
            err_cb,
        )

    def set_platform_layout(self, layout):
        index = self.__input_sources.get(layout)
        log("set_platform_layout(%s): index=%s", layout, index)
        if index is None:
            log(f"asked layout ({layout}) has no corresponding registered input source")
            return
        self._dbus_gnome_shell_eval_ism(
            f".inputSources[{index}].activate()",
        )

    def __repr__(self):
        return "posix.Keyboard"

    def get_keymap_modifiers(self):
        if self.keymap_modifiers is None:
            self.keymap_modifiers = self.do_get_keymap_modifiers()
        return self.keymap_modifiers

    def do_get_keymap_modifiers(self):
        if not self.keyboard_bindings:
            if is_Wayland():
                log.warn("Warning: incomplete keymap support under Wayland")
                return {}, [], ["mod2", ]
            return {}, [], []
        try:
            with xsync:
                mod_mappings = self.keyboard_bindings.get_modifier_mappings()
                if mod_mappings:
                    #ie: {"shift" : ["Shift_L", "Shift_R"], "mod1" : "Meta_L", ...]}
                    log("modifier mappings=%s", mod_mappings)
                    meanings = {}
                    for modifier,keys in mod_mappings.items():
                        for _,keyname in keys:
                            meanings[keyname] = modifier
                    #probably a GTK bug? but easier to put here
                    mod_missing = []
                    numlock_mod = meanings.get("Num_Lock", [])
                    if numlock_mod:
                        mod_missing.append(numlock_mod)
                    return  meanings, [], mod_missing
        except Exception:
            log.error("failed to use native get_modifier_mappings", exc_info=True)
        return {}, [], []

    def get_x11_keymap(self):
        if not self.keyboard_bindings:
            return  {}
        try:
            with xsync:
                return self.keyboard_bindings.get_keycode_mappings()
        except Exception:
            log.error("Error: failed to use raw x11 keymap", exc_info=True)
        return  {}

    def get_locale_status(self):
        #parse the output into a dictionary:
        # $ localectl status
        # System Locale: LANG=en_GB.UTF-8
        # VC Keymap: gb
        # X11 Layout: gb
        from subprocess import getoutput  # pylint: disable=import-outside-toplevel
        out = getoutput("localectl status")
        if not out:
            return {}
        locale = {}
        for line in bytestostr(out).splitlines():
            parts = line.lstrip(" ").split(": ")
            if len(parts)==2:
                locale[parts[0]]=parts[1]
        log("locale(%s)=%s", out, locale)
        return locale

    def get_keymap_spec(self):
        log("get_keymap_spec() keyboard_bindings=%s", self.keyboard_bindings)
        if is_Wayland() or not self.keyboard_bindings:
            locale = self.get_locale_status()
            query_struct = {}
            if locale:
                layout = locale.get("X11 Layout")
                if layout:
                    query_struct["layout"] = layout
            log("query_struct(%s)=%s", locale, query_struct)
            return query_struct
        with xsync:
            query_struct = self.keyboard_bindings.getXkbProperties()
        log("get_keymap_spec()=%r", query_struct)
        return query_struct


    def get_xkb_rules_names_property(self):
        #parses the "_XKB_RULES_NAMES" X11 property
        if not is_X11():
            return ""
        xkb_rules_names = ""
        # pylint: disable=import-outside-toplevel
        from xpra.gtk_common.error import xlog
        from xpra.x11.common import get_X11_root_property
        with xlog:
            prop = get_X11_root_property("_XKB_RULES_NAMES", "STRING")
            log("get_xkb_rules_names_property() _XKB_RULES_NAMES=%s", prop)
            #ie: 'evdev\x00pc104\x00gb,us\x00,\x00\x00'
            if prop:
                xkb_rules_names = bytestostr(prop).split("\0")
            #ie: ['evdev', 'pc104', 'gb,us', ',', '', '']
        log("get_xkb_rules_names_property()=%s", xkb_rules_names)
        return xkb_rules_names


    def get_all_x11_layouts(self):
        repository = "/usr/share/X11/xkb/rules/base.xml"
        if os.path.exists(repository):
            try:
                import lxml.etree  #pylint: disable=import-outside-toplevel
            except ImportError:
                log("cannot parse xml", exc_info=True)
            else:
                try:
                    with open(repository, "r", encoding="latin1") as f:
                        tree = lxml.etree.parse(f)  #pylint: disable=c-extension-no-member @UndefinedVariable
                except Exception:
                    log.error(f"Error parsing {repository}", exc_info=True)
                else:
                    x11_layouts = {}
                    for layout in tree.xpath("//layout"):
                        layout = layout.xpath("./configItem/name")[0].text
                        x11_layouts[layout] = layout
                        #for variant in layout.xpath("./variantList/variant/configItem/name"):
                        #    variant_name = variant.text
                    return x11_layouts
        from subprocess import Popen, PIPE  #pylint: disable=import-outside-toplevel
        try:
            proc = Popen(["localectl", "list-x11-keymap-layouts"], stdout=PIPE, stderr=PIPE)
            out = proc.communicate()[0]
            log("get_all_x11_layouts() proc=%s", proc)
            log("get_all_x11_layouts() returncode=%s", proc.returncode)
            if proc.wait()==0:
                x11_layouts = {}
                for line in out.splitlines():
                    layout = line.decode().split("/")[-1]
                    if layout:
                        x11_layouts[layout] = layout
                return x11_layouts
        except OSError:
            log("get_all_x11_layouts()", exc_info=True)
        return {"us" : "English"}


    def get_layout_spec(self):
        layout = ""
        layouts = []
        variant = ""
        options = ""
        v = None
        if self.keyboard_bindings:
            with xsync:
                props = self.keyboard_bindings.getXkbProperties()
            v = props.get("layout")
            variant = props.get("variant", "")
            options = props.get("options", "")
        else:
            locale = self.get_locale_status()
            v = locale.get("X11 Layout")
        if not v:
            #fallback:
            v = self.get_xkb_rules_names_property()
            #ie: ['evdev', 'pc104', 'gb,us', ',', '', '']
            if v and len(v)>=3:
                v = v[2]
        if v:
            layouts = v.split(",")
            layout = v
        def s(v):
            try:
                return v.decode("latin1")
            except Exception:
                return str(v)
        return s(layout), [s(x) for x in layouts], variant, None, options


    def get_keyboard_repeat(self):
        v = None
        if self.keyboard_bindings:
            try:
                v = self.keyboard_bindings.get_key_repeat_rate()
                if v:
                    assert len(v)==2
            except Exception as e:
                log.error("Error: failed to get keyboard repeat rate:")
                log.estr(e)
                v = None
        log("get_keyboard_repeat()=%s", v)
        return v

    def update_modifier_map(self, display, mod_meanings):
        try:
            # pylint: disable=import-outside-toplevel
            from xpra.x11.gtk_x11.keys import grok_modifier_map
            self.modifier_map = grok_modifier_map(display, mod_meanings)
        except ImportError:
            self.modifier_map = MODIFIER_MAP
        #force re-query on next call:
        self.keymap_modifiers = None
        try:
            classname = type(display).__name__
            dn = f"{classname} "+display.get_name()
        except Exception:
            dn = str(display)
        log(f"update_modifier_map({dn}, {mod_meanings}) modifier_map={self.modifier_map}")