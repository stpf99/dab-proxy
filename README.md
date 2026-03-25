prerun desktop app time to time "abracadabra" dab app for collecting epg data

1.   welle-cli -c 11A -D -w 7979   -F rtl_tcp,192.168.1.1:1234
2.   python3 abradab2kodi.py --stream-base http://localhost:7979
3.   ~/kodi_dab:
      epg.xml  playlist.m3u << m3u xml for iptv-simple kodi pvr addon ...
     

<img width="964" alt="diseqc" src="https://github.com/stpf99/dab-proxy/blob/1ac5f136caba5415095010ca498cd9df885d59a2/Zrzut%20ekranu%20z%202026-03-22%2019-17-24.png">

<img width="964" alt="diseqc" src="https://github.com/stpf99/dab-proxy/blob/690849303f1e4ab3e6b4d1c7a540d8555b092b84/Zrzut%20ekranu%20z%202026-03-22%2019-15-20.png">


dab2kodi-install.zip have all files (systemd and py sh ) with welle-cli (x86_64 /libs) libreelec x86_64 compatybile/not tested

rtl_tcp with instance on 192.168.1.1:1234 by default
