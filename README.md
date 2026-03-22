alpha script

prerun "abracadabra" dab app for collecting epg data

1.   welle-cli -c 11A -D -w 7979   -F rtl_tcp,192.168.1.1:1234
2.   python3 abradab2kodi.py --stream-base http://localhost:7979
3.   ~/kodi_dab:
      epg.xml  playlist.m3u << m3u xml for iptv-simple kodi pvr addon ...
     
