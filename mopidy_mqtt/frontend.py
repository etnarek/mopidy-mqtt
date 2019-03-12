# future imports
from __future__ import absolute_import
from __future__ import unicode_literals

# stdlib imports
import logging
import time

from mopidy import core

import paho.mqtt.client as mqtt

# third-party imports
import pykka

logger = logging.getLogger(__name__)

class MQTTFrontend(pykka.ThreadingActor, core.CoreListener):

    def __init__(self, config, core):
        logger.info("mopidy_mqtt initializing ... ")
        self.core = core
        self.mqttClient = mqtt.Client(client_id="mopidy-" + str(int(round(time.time() * 1000))), clean_session=True)
        self.mqttClient.on_message = self.mqtt_on_message
        self.mqttClient.on_connect = self.mqtt_on_connect     
        
        self.config = config['mqtthook']
        host = self.config['mqtthost']
        port = self.config['mqttport']
        self.topic = self.config['topic']
        if self.config['username'] and self.config['password']:
            self.mqttClient.username_pw_set(self.config['username'], password=self.config['password'])
        self.mqttClient.connect_async(host, port, 60)        
        
        self.mqttClient.loop_start()
        super(MQTTFrontend, self).__init__()
        self.MQTTHook = MQTTHook(self, core, config, self.mqttClient)
        
    def mqtt_on_connect(self, client, userdata, flags, rc):
        logger.info("Connected with result code %s" % rc)
        
        rc = self.mqttClient.subscribe(self.topic + "/play")
        if rc[0] != mqtt.MQTT_ERR_SUCCESS:            
            logger.warn("Error during subscribe: " + str(rc[0]))
        else:
            logger.info("Subscribed to " + self.topic + "/play")
        self.mqttClient.subscribe(self.topic + "/control")
        logger.info("sub:" + self.topic + "/control")
        self.mqttClient.subscribe(self.topic + "/volume")
        logger.info("sub:" + self.topic + "/volume")
        self.mqttClient.subscribe(self.topic + "/add")
        logger.info("sub:" + self.topic + "/add")

    def mqtt_on_message(self, mqttc, obj, msg):
        logger.info("received a message on " + msg.topic+" with payload "+str(msg.payload))
        topPlay = self.topic + "/play"
        topControl = self.topic + "/control"
        topVolume = self.topic + "/volume"
        topAdd = self.topic + "/add"

        if msg.topic == topPlay:
            self.core.tracklist.clear()
            self.core.tracklist.add(None, None, str(msg.payload), None)
            self.core.playback.play()
        if msg.topic == topAdd:
            self.core.tracklist.add(None, None, str(msg.payload), None)
        elif msg.topic == topControl:
            if msg.payload == "stop":
                self.core.playback.stop()
            elif msg.payload == "pause":
                self.core.playback.pause()
            elif msg.payload == "play":
                self.core.playback.play()
            elif msg.payload == "resume":
                self.core.playback.resume()
            elif msg.payload == "next":
                self.core.playback.next()
            elif msg.payload == "previous":
                self.core.playback.previous()
            elif msg.payload == "clear":
                self.core.tracklist.clear()
            elif msg.payload == "toggle":
                state = self.core.playback.get_state().get()
                if state == "paused":
                    self.core.playback.resume()
                elif state == "stopped":
                    self.core.playback.play()
                elif state == "playing":
                    self.core.playback.pause()
        elif msg.topic == topVolume:
            volume = 0
            if msg.payload[0].strip() in ["+", "-"]:
                volume = self.core.mixer.get_volume().get()
            try:
                volume += int(msg.payload)
                self.core.mixer.set_volume(volume)
            except ValueError:
                logger.warn("invalid payload for volume: " + msg.payload)

    def on_stop(self):
        logger.info("mopidy_mqtt shutting down ... ")
        self.mqttClient.disconnect()
        
    def stream_title_changed(self, title):
        self.MQTTHook.publish("/nowplaying", title)
        self.tracklist_changed()

    def playback_state_changed(self, old_state, new_state):
        self.MQTTHook.publish("/state", new_state)
        if (new_state == "stopped"):
            self.MQTTHook.publish("/nowplaying", "stopped")

    def tracklist_changed(self):
        track = self.core.tracklist.next_track(None).get()
        if track:
            track = track.track
        if track:
            artists = ', '.join(sorted([a.name for a in track.artists]))
            self.MQTTHook.publish("/nextplaying", artists + ":" + track.name)
        else:
            self.MQTTHook.publish("/nextplaying", "No next")
        
    def track_playback_started(self, tl_track):
        track = tl_track.track
        artists = ', '.join(sorted([a.name for a in track.artists]))
        self.MQTTHook.publish("/nowplaying", artists + ":" + track.name)
        try:
            album = track.album
            albumImage = next(iter(album.images))
            self.MQTTHook.publish("/image", albumImage)
        except:
            logger.debug("no image")
        self.tracklist_changed()
        
class MQTTHook():
    def __init__(self, frontend, core, config, client):
        self.config = config['mqtthook']        
        self.mqttclient = client
       
    def publish(self, topic, state):
        full_topic = self.config['topic'] + topic
        try:
            rc = self.mqttclient.publish(full_topic, state, retain=True)
            if rc[0] == mqtt.MQTT_ERR_NO_CONN:            
                logger.warn("Error during publish: MQTT_ERR_NO_CONN")
            else:
                logger.info("Sent " + state + " to " + full_topic)
        except Exception as e:
            logger.error('Unable to send', exc_info=True)
