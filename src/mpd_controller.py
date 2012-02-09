import time
import sys
import os
import serial
from optparse import OptionParser
import logging
import mpd


HOST = "kenshi-desktop"

class SensorBuffer:
    def __init__(self,buf_size):
        self.buf_size = buf_size
        self.buffer = []

    def add(self,val):
        if(len(self.buffer) == self.buf_size):
            self.buffer.pop(0)
        self.buffer.append(val)
        return self.value()

    def value(self):
        return reduce(lambda x, y: x+y,self.buffer)/len(self.buffer)

class SerialReader:
    def __init__(self, ser):
        self.ser = ser

    def getSensorValues(self):
        val = None
        while(None == val or len(val) < 3):
            self.ser.write("1")  # Writing any charachter will act as an ACK
            val = self.ser.readline()
        sensor1 = ord(val[0])
        sensor2 = ord(val[1])
        sensor3 = ord(val[2])
        return [sensor1, sensor2, sensor3]

class MockSerialReader:
    def __init__(self):
        return

    def getSensorValues(self):
        return 255, 255, 4

class Playlist(object):
    def __init__(self, name, times):
        """
        name: playlist name
        times: the song lengths in seconds
        """
        self.name = name
        self.times = times

    @property
    def num_songs(self):
        return len(self.times)

    @property
    def running_time_secs(self):
        if not hasattr(self, '_running_time_secs'):
            self._running_time_secs = sum(self.times)
        return self._running_time_secs

    @property
    def running_time_mins(self):
        return self.running_time_secs/60

    def get_song_index_and_offset(self, time):
        offset_time = time % self.running_time_secs # In case the playlist has looped

        total = 0
        for i, t in enumerate(self.times):
            if total + t > offset_time:
                return i, offset_time - total
            total += t

        # Shouldn't ever get here
        assert False


    def __repr__(self):
        return "%s [%i songs and %i minutes]" % (self.name, self.num_songs, self.running_time_mins)

    def __eq__(self, other):
        # Crude, but it should work in most cases
        return (type(self) == type(other)) and (self.name == other.name) and (self.num_songs == other.num_songs)

    def __ne__(self, other):
        return not self.__eq__(other)

class JukeBox:
    def __init__(self, client, serial_reader, options = {}):
        self.ser = serial_reader
        self.client = client
        self.run_flag = True
        self.current_playlist = None
        self.set_playlists()
        self.station_low, self.station_high = [int(i) for i in options.station_range.split('-')]
        self.verbose = options.verbose
        self.vol = 0

        self._time = 0

    @property
    def time(self):
        return int(self._time)

    def get_playlist_info(self):
        info = self.client.lsinfo()
        playlists = []
        for item in info:
            if item.has_key('playlist'):
                playlists.append(item)
        return playlists

    def new_playlists_available(self):
        existing = self.playlists
        new_playlists = self.get_playlists()

        if len(existing) != len(new_playlists):
            return True

        new_pl_hash = {}
        for pl in new_playlists:
            new_pl_hash[pl.name] = pl

        for pl in existing:
            pl_missing = not new_pl_hash.has_key(pl.name)
            pl_changed = (new_pl_hash.get(pl.name) != pl)
            if pl_missing or pl_changed:
                return True

        return False


    def set_playlists(self):
        playlists = self.get_playlists()
        if len(playlists) < 1:
            raise "Error: No playlists exist currently.  Please add some and try again"
        self.playlists = playlists

    def get_playlists(self):
        try:
            info = self.client.lsinfo()
        except mpd.ConnectionError, e:
            info = self.client.lsinfo()

        playlists = []
        for item in info:
            if not item.has_key('playlist'):
                continue
            name = item['playlist']
            pl_info = self.client.listplaylistinfo(name)
            try:
                times = [int(song['time']) for song in pl_info]
            except:
                logging.error("Problem with playlist: %s" % song)
                raise
            playlists.append(Playlist(name, times))

        return sorted(playlists, key=lambda pl: pl.name)

    def switch_stations(self, sensor):
        increment = (self.station_high - self.station_low)/len(self.playlists)
        station_index = int((sensor-self.station_low)/increment)
        if station_index >= len(self.playlists):
            station_index = len(self.playlists) -1

        playlist = self.playlists[station_index]
        if playlist != self.current_playlist:
            self.current_playlist = playlist
            i, o  = self.current_playlist.get_song_index_and_offset(self.time)
            logging.info("Playlist: %s SongID: %i Offset: %i secs Total Time: %i" % (playlist.name, i, o, self.time))
            self.client.pause()
            self.client.clear()
            self.client.load(playlist.name)
            self.client.seek(i, o)
            self.client.play()

    def set_volume(self, sensor_buffer):
        vol = int(sensor_buffer.value()/255.00 *100)
        if abs(vol - self.vol) > 1:
            self.client.setvol(vol)
            self.vol = vol

    def send_heartbeat(self):
        """
        Unless you periodically send a signal to the client, the
        connection dies in shitty ways.

        Just issue an arbitrary command, but may as well get the
        current status and store it somewhere.
        """
        self._status = self.client.status()

    def run(self):
        self.client.play()
        sensorBuffer1 = SensorBuffer(4)
        sensorBuffer2 = SensorBuffer(4)
        sensorBuffer3 = SensorBuffer(4)

        i = 0
        prev_vol = 0
        while(self.run_flag):
            i += 1
            t1 = time.time()
            sensor1, sensor2, sensor3 = self.ser.getSensorValues()
            sensorBuffer1.add(sensor1)
            sensorBuffer2.add(sensor2)
            sensorBuffer3.add(sensor3)
            if self.verbose:
                vals = [s.value() for s in [sensorBuffer1, sensorBuffer2, sensorBuffer3]]
                print vals
            self.set_volume(sensorBuffer3)
            self.switch_stations(sensorBuffer1.value())
            time.sleep(0.1)

            if i == 10:
                self.send_heartbeat() # Heartbeat every second or so
                i = 0

            # Potential race condition... but oh well
            # Load playlists every , if there are any...
            if i==1 and self.time % 60 == 0 and self.new_playlists_available():
                logging.info( "New playlists available!  Loading now... standby")
                self.set_playlists()
            t2 = time.time()
            self._time += (t2 - t1)
        return 0

class MockJukeBox(object):
    def __init__(self, ser):
        self.ser = ser

    def run(self):
        while True:
            print self.ser.getSensorValues()
            time.sleep(0.1)


def setup_logging(log_file, log_level):
    logger = logging.getLogger()
    logger.setLevel(log_level)

    if isinstance(log_file, file):
        handler = logging.StreamHandler(log_file)
    else:
        handler = logging.FileHandler(os.path.expanduser(log_file), 'a')
    handler.setLevel(log_level)

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(process)d - %(message)s")
    handler.setFormatter(formatter)

    logger.addHandler(handler)

def main(options, args):
    setup_logging(options.log_file, logging.DEBUG)

    if options.mock_sensors:
        ser = MockSerialReader()
    else:
        ser = SerialReader(serial.Serial(options.usb_serial, options.baud, timeout=0.3))

    if options.debug_sensors:
        jukebox = MockJukeBox(ser)
    else:

        client = mpd.MPDClient()           # create client object
        client.connect(options.host, 6600)

        # Should probably extract only what we need
        jukebox_options = options

        jukebox = JukeBox(client, ser, options=jukebox_options)

    try:
        jukebox.run()
    except Exception:
        logging.exception("Jukebox Failed!")


if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option('-m', '--mock-sensors', dest='mock_sensors',
                      help='Mock out Arduino', action='store_true', default=False)
    parser.add_option('--host', dest='host',
                      help='MPD host', default='localhost')
    parser.add_option('-b', '--baud', dest='baud',
                      help='Serial baud rate', type='int', default=9600)
    parser.add_option('-d', '--debug-sensors', dest='debug_sensors',
                      help='Print sensors to console', action='store_true', default=False)
    parser.add_option('-u', '--usb-serial', dest='usb_serial', default="/dev/ttyUSB0",
                      help='Set the usb serial device [%default]')
    parser.add_option('--station-range', dest='station_range', default='0-255',
                      help='What is the range of the station value. [%default]')
    parser.add_option('-v', '--verbose',  dest='verbose', default=False,
                      help='Verbose output [%default]')
    parser.add_option('--log', dest='log_file', default=sys.stdout,
                      help='Logfile out (default is stdout)')
    (options, args) = parser.parse_args()
    sys.exit(main(options, args))
