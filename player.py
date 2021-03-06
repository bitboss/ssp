#!/usr/bin/env python2
# -*- coding: utf-8 -*-
#
#  Copyright (C) 2012  James Adams
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#


# Icky work-around for the gst module setting up it's own parser... the bastard...
import argparse
parser = argparse.ArgumentParser(description='Super Simple Player')
parser.add_argument('--passive', action='store_true', help="Don't update track statistics or delete missing tracks.")
args = parser.parse_args()
del parser

import sys, os
import pygtk, gtk, gobject
import pygst
pygst.require("0.10")
import pango
from gst import element_factory_make, STATE_PLAYING, STATE_NULL, MESSAGE_EOS, MESSAGE_ERROR, MESSAGE_TAG
from datetime import datetime
import logging
import pynotify

from library import *


class TrackInfo:
    def __init__(self):
        self.title = ""
        self.artist = ""
        self.album = ""
        self.year = ""

    def tolabel(self):
        return "%s\n%s\n%s (%s)" % (self.title, self.artist, self.album, self.year)

    def totitle(self):
        return "SSP : %s - %s - %s (%s)" % (self.title, self.artist, self.album, self.year)

    def tonotification(self):
        return (self.title, ("%s\n%s (%s)" % (self.artist, self.album, self.year)))


class Player:

    def __init__(self, passive=False):
        self.logger = logging.basicConfig(filename='%s/ssp.log' % os.path.dirname(sys.argv[0]), level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S', name="ssp")
        self.logger = logging.getLogger("ssp")
        self.logger.info("Startup, passive mode %s" % passive)

        self.passive = passive
        self.trackinfo = TrackInfo()
        self.library = connect()

        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.set_title("SSP")

        self.window.connect("destroy", gtk.main_quit, "WM destroy")
        self.window.connect("delete_event", self.key_press)
        self.window.connect("key_press_event", self.key_press)

        self.window.modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse("#000"))

        self.label = gtk.Label()

        self.label.modify_font(pango.FontDescription("Sans 32"))
        self.label.set_alignment(0.5, 0.5)
        self.label.modify_fg(gtk.STATE_NORMAL, gtk.gdk.color_parse("#eeeeec"))
        self.label.set_line_wrap(True)

        self.window.add(self.label)

        self.window.show_all()

        self.player = element_factory_make("playbin2", "player")
        fakesink = element_factory_make("fakesink", "fakesink")
        self.player.set_property("video-sink", fakesink)

        bus = self.player.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)

        pynotify.init("SSP")
        self.notification = pynotify.Notification("SSP")


    def key_press(self, widget, event, data=None):
        #Only exit if window is closed or Escape key is pressed
        if event.type == gtk.gdk.KEY_PRESS and gtk.gdk.keyval_name(event.keyval) == "space":
            self.skip()
            return True
        elif event.type == gtk.gdk.KEY_PRESS and gtk.gdk.keyval_name(event.keyval) != "Escape":
            return True
        else:
            gtk.main_quit()
            return False


    def play(self):
        self.track = self.library.query(sspTrack).order_by(sspTrack.playcount + sspTrack.skipcount, "random()").first()
        self.stat = self.library.query(sspStat).filter("hour = %s" % datetime.now().hour).first()
        self.trackinfo = TrackInfo()

        if os.path.isfile(self.track.filepath):
            self.player.set_property("uri", "file://" + self.track.filepath)
            self.player.set_state(STATE_PLAYING)
        else:
            self.logger.info("Oops, \"%s\" doesn't seem to exist anymore" % self.track.filepath)
            self.stop()
            if not self.passive:
                self.logger.warning("Removing \"%s\" from the library." % self.track.filepath)
                self.library.delete(self.track)
                self.library.commit()
            self.play()


    def skip(self):
        self.stop()
        if not self.passive:
            # Increment skip count
            self.track.skipcount += 1
            self.stat.skipcount += 1
            self.library.commit()
        self.play()


    def stop(self):
        self.player.set_state(STATE_NULL)


    def on_message(self, bus, message):
        t = message.type

        if t == MESSAGE_EOS: # End Of Stream
            self.stop()
            if not self.passive:
                # Increment play count, set last played
                self.track.playcount += 1
                self.stat.playcount += 1
                self.track.lastplayed = datetime.now()
                self.library.commit()
            self.play()

        elif t == MESSAGE_ERROR: # Eeek!
            self.stop()
            err, debug = message.parse_error()
            self.logger.error("MESSAGE_ERROR: %s" % err, debug)

        elif t == MESSAGE_TAG:
                taglist = message.parse_tag()
                keys = taglist.keys()
                if "title" in taglist:
                    self.trackinfo.title = taglist["title"]
                    if "artist" in taglist:
                        self.trackinfo.artist = taglist["artist"]
                    if "album" in taglist:
                        self.trackinfo.album = taglist["album"]
                        if "date" in taglist:
                            self.trackinfo.year = str(taglist["date"].year)

                    self.label.set_label(self.trackinfo.tolabel())
                    self.window.set_title(self.trackinfo.totitle())
                    self.notify(self.trackinfo.tonotification())


    def notify(self, message):
        self.notification.update(message[0], message[1], "media-skip-forward")
        self.notification.show()


if __name__ == "__main__":
    p = Player(args.passive)
    p.play()
    gtk.main()
