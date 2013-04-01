#!/usr/bin/python
# -*- coding: utf-8 -*-

import smtplib
import ConfigParser
import time
import hashlib
import socket
import imaplib2
import argparse
import sys
import threading
import re

from email.mime.text import MIMEText
from email.parser import Parser

class ImapIdler(threading.Thread): # {{{

    def __init__(self, imapobject, subject_prefix, debug=False, imapfolder='INBOX'):
        threading.Thread.__init__(self)
        self.imapobject = imapobject
        self.imapfolder = imapfolder
        self.subject_prefix = subject_prefix
        self.__stop = threading.Event()
        self.__debug = debug
        self.__last_id = False
        self.__new_id = False

        self.__result_store = {}

    def run(self):
        # fetch last ids available
        self.__last_id = self.imapobject.select(self.imapfolder)[1][0]

        while True:
            if self.__stop.isSet():
                return
            else:
                try:
                    result = self.imapobject.idle(10)
                    if result[0] == 'OK':
                        if self.__debug:
                            print 'Timeout or Event when IDLE!'
                        if self.imapobject.response('IDLE')[1][0] == None:
                            new_id = self.imapobject.response('EXISTS')
                            if self.__debug:
                                print 'IMAP-EXISTS-response: ' + str(new_id)
                            if new_id[1][0] != None:
                                self.__new_id = new_id[1][0]
                                self.parse_new_emails()
                except:
                    raise # FIXME: Errorhandling needed

    def parse_new_emails(self):
        while self.__new_id > self.__last_id:
            self.__last_id = str(int(self.__last_id) + 1)

            if self.__debug:
                print "parsing mailid: " + self.__last_id

            header = self.imapobject.fetch(self.__last_id, '(BODY[HEADER.FIELDS subject])')
            if self.__debug:
                print 'Headers fetched: ' + str(header)
            if header[0] == 'OK' and header[1][0] != None: # FIXME: Errorhandling needed
                if type(header[1][0]).__name__ == 'tuple': # that is really crazy but the result from fetch....can be strange!
                    header = header[1][0]
                else:
                    header = header[1][1]
                substring = 'Subject: ' + re.sub('\|','\\\|',re.sub('\]','\\\]',re.sub('\[','\\\[',self.subject_prefix)))
                my_id = re.sub(substring,'',header[1].strip())
                if my_id in self.__result_store:
                    raise Exception('duplicate Mail?')
                else:
                    if self.__debug:
                        print "found id: " + my_id
                    self.__result_store.update({ my_id : time.time() })

    def stop(self):
        self.__stop.set()
        self.imapobject.logout()

    def get_ids(self):
        return self.__result_store
# }}}

class Account(object): # {{{
    """docstring for Account"""
    def __init__(self, name, login=False, password=False, smtp_server="localhost", imap_server="localhost", imap_timeout="600", smtp_over_ssl=False, use_imap_idle=False): # {{{
        super(Account, self).__init__()
        self.name           =   name
        self.login          =   login
        self.password       =   password
        self.smtp_server    =   smtp_server
        self.imap_server    =   imap_server
        self.email          =   login
        self.imap_timeout   =   imap_timeout

        self.__debug        =   False
        self.smtp_over_ssl  =   smtp_over_ssl

        self.subject_prefix = "[SMTP-GEE] |"

        self.imap_idle      =   use_imap_idle
    # }}}

    def send(self, recipient): # {{{
        """docstring for send"""

        timestamp = time.time()

        payload = """Hi,
this is a testmail, generated by SMTP-GEE.

sent on:   %s
sent at:   %s
sent from: %s
sent to:   %s

Cheers.
    SMTP-GEE

""" % (socket.getfqdn(), timestamp, self.email, recipient.email, )


        test_id = hashlib.sha1(payload).hexdigest()


        msg = MIMEText(payload)

        msg['From']     =   self.email
        msg['To']       =   recipient.email
        msg['Subject']  =   self.subject_prefix + test_id

        try:
            if self.smtp_over_ssl:
                if self.__debug: print "SMTP-over-SSL is used"
                s = smtplib.SMTP_SSL( self.smtp_server )
            else:
                if self.__debug: print "SMTP is used"
                s = smtplib.SMTP( self.smtp_server )
                s.starttls()

            #s.set_debuglevel(2)
            s.login(self.login, self.password )

            s.sendmail( self.email, recipient.email, msg.as_string() )
            s.quit()

            return test_id

        except:
            return False


    # }}}

    def start_idle(self):
        self.ImapIdle(start=True)

    def ImapIdle(self, check_id=None, start=False):
        if start:
            m = imaplib2.IMAP4_SSL(self.imap_server)

            m.login(self.login, self.password)
            m.select()

            self.idler = ImapIdler(m, self.subject_prefix, self.__debug)
            self.idler.start()
        else:
            if check_id == None:
                raise Exception('Missing check_id')
            else:
                check_start = int(time.time())
                check_now = check_start
                while (check_now - check_start) < self.imap_timeout:
                    results = self.idler.get_ids()
                    if check_id in results:
                        self.idler.stop()
                        self.idler.join()
                        return True, results[check_id]
                    else:
                        time.sleep(1)
                        check_now = int(time.time())
                else:
                    self.idler.stop()
                    self.idler.join()
                    return False, None

    def ImapSearch(self, imapobject, check_id):
        data=[]

        # Wait until the message is there.
        check_start = int(time.time())
        check_now = check_start
        while data == [] and (check_now - check_start) < self.imap_timeout:
            typ, data = imapobject.search(None, 'SUBJECT', '"%s"' % check_id)
            time.sleep(1)
            check_now = int(time.time())

        timestamp = time.time()

        if data != []:
            result = True
            for num in data[0].split():
                typ, data = imapobject.fetch(num, '(RFC822)')
                # print typ
                msg = data[0][1]

            headers = Parser().parsestr(msg)

            if self.__debug:
                for h in headers.get_all('received'):
                    print "---"
                    print h.strip('\n')
        else:
            result = False

        # deleting should be more sophisticated, for debugging...
        #m.store(num, '+FLAGS', '\\Deleted')
        imapobject.close()
        imapobject.logout()
        return result, timestamp


    def check(self, check_id): # {{{
        """docstring for check"""
        if self.imap_idle:
            return self.ImapIdle(check_id)
        else:
            m = imaplib2.IMAP4_SSL(self.imap_server)

            m.login(self.login, self.password)
            m.select()

            return self.ImapSearch(m, check_id)
    # }}}

    def set_debug(self, debug): # {{{
        """docstring for set_debug"""
        self.__debug = debug

    # }}}

# }}}

class Stopwatch(object): # {{{
    """docstring for Stopwatch"""
    def __init__(self, debug=False):
        super(Stopwatch, self).__init__()
        self.__debug = debug
        self.__start   = -1
        self.counter = 0

    def start(self, my_time=time.time()):
        """docstring for start"""
        self.__start = my_time

    def stop(self, my_time=time.time()):
        """docstring for stop"""
        if my_time == None:
            my_time = time.time()
        self.counter += my_time - self.__start
        self.__start  = -1
# }}}

if __name__ == "__main__":

    # fallback returncode
    returncode = 3

    # Parse Options # {{{
    parser = argparse.ArgumentParser(
        description='Check how long it takes to send a mail (by SMTP) and how long it takes to find it in the IMAP-inbox',
        epilog = "Because e-mail is a realtime-medium and you know it!")


    main_parser_group = parser.add_argument_group('Main options')
    main_parser_group.add_argument('--from', dest='sender', action='store',
                    required=True,
                    metavar="<name>",
                    help='The account to send the message')

    main_parser_group.add_argument('--rcpt', dest='rcpt', action='store',
                    required=True,
                    metavar="<name>",
                    help='The account to receive the message')

    main_parser_group.add_argument('--nagios', dest='nagios', action='store_true',
                    required=False,
                    default=False,
                    help='output in Nagios mode')

    main_parser_group.add_argument('--debug', dest='debug', action='store_true',
                    required=False,
                    default=False,
                    help='Debug mode')

    main_parser_group.add_argument('--config',dest='config_file', action='store',
                    default='config.ini',
                    metavar="<file>",
                    required=False,
                    help='alternate config-file')


    smtp_parser_group = parser.add_argument_group('SMTP options')
    smtp_parser_group.add_argument('--smtp_warn', dest='smtp_warn', action='store',
                    required=False,
                    default=15,
                    metavar="<sec>",
                    type=int,
                    help='warning threshold to send the mail. Default: %(default)s')

    smtp_parser_group.add_argument('--smtp_crit', dest='smtp_crit', action='store',
                    required=False,
                    default=30,
                    metavar="<sec>",
                    type=int,
                    help='critical threshold to send the mail. Default: %(default)s')

    smtp_parser_group.add_argument('--smtp_timeout', dest='smtp_timeout', action='store',
                    required=False,
                    default=60,
                    metavar="<sec>",
                    type=int,
                    help='timeout to stop sending a mail (not implemented yet). Default: %(default)s')


    imap_parser_group = parser.add_argument_group('IMAP options')
    imap_parser_group.add_argument('--imap_warn', dest='imap_warn', action='store',
                    required=False,
                    default=120,
                    metavar="<sec>",
                    type=int,
                    help='warning threshold until the mail appears in the INBOX. Default: %(default)s')

    imap_parser_group.add_argument('--imap_crit', dest='imap_crit', action='store',
                    required=False,
                    default=300,
                    metavar="<sec>",
                    type=int,
                    help='critical threshold until the mail appears in the INBOX. Default: %(default)s')

    imap_parser_group.add_argument('--imap_timeout', dest='imap_timeout', action='store',
                    required=False,
                    default=600,
                    metavar="<sec>",
                    type=int,
                    help='timeout to stop waiting for a mail to appear in the INBOX (not implemented yet). Default: %(default)s')

    imap_parser_group.add_argument('--imap_idle', dest='imap_idle', action='store_true',
                    default=False,
                    help='Use IMAP IDLE')

    args = parser.parse_args()

    # }}}

    # Read Config {{{

    c = ConfigParser.ConfigParser()
    c.read(args.config_file)

    a={}

    for s in c.sections():
        a[s] = Account(s)

        a[s].set_debug(args.debug)

        # This has to be more easy...
        a[s].smtp_server = c.get(s, 'smtp_server')
        a[s].imap_server = c.get(s, 'imap_server')
        a[s].password    = c.get(s, 'password')
        a[s].login       = c.get(s, 'login')
        a[s].email       = c.get(s, 'email')

        # FIXME: do that via SET method maybe
        a[s].imap_timeout = args.imap_timeout
        if s == args.rcpt:
            if args.imap_idle:
                a[s].imap_idle = args.imap_idle
                a[s].start_idle()
        
        try:
            a[s].smtp_over_ssl = c.get(s, 'smtp_over_ssl')
        except:
            pass

    # }}}

    ### Here the real work begins  ###

    # Create the stopwatches.
    smtp_time = Stopwatch()
    imap_time = Stopwatch()

    # send the mail by SMTP
    smtp_time.start()
    smtp_sender = a[args.sender].send(a[args.rcpt])
    smtp_time.stop()

    if args.debug:
        print "Test-ID: " + smtp_sender

    if smtp_sender:

        # Receive the mail.
        imap_time.start()
        result, stoptime = a[args.rcpt].check(smtp_sender)
        imap_time.stop(stoptime)

    ### Present the results

    if not args.nagios:

        # Default output
        print "SMTP, (%s) time to send the mail: %.3f sec." % (args.sender, smtp_time.counter, )
        print "IMAP, (%s) time until the mail appeared in the destination INBOX: %.3f sec." % (args.rcpt, imap_time.counter, )

    else:

        # Nagios output
        # this could be beautified...

        nagios_code = ('OK', 'WARNING', 'CRITICAL', 'UNKNOWN' )

        if   ((smtp_time.counter >= args.smtp_crit) or (imap_time.counter >= args.imap_crit)):
            returncode = 2
        elif ((smtp_time.counter >= args.smtp_warn) or (imap_time.counter >= args.imap_warn)):
            returncode = 1
        else:
            returncode = 0

        if not smtp_sender or result == False: # if it failed
            returncode = 3
            nagios_template="%s: (%s->%s) SMTP failed in %.3f sec, NOT received in %.3f sec|smtp=%.3f;%.3f;%.3f, imap=%.3f;%.3f;%.3f"
        else:
            nagios_template="%s: (%s->%s) sent in %.3f sec, received in %.3f sec|smtp=%.3f;%.3f;%.3f, imap=%.3f;%.3f;%.3f"

        print nagios_template % (
            nagios_code[returncode],
            args.sender,
            args.rcpt,
            smtp_time.counter,
            imap_time.counter,
            smtp_time.counter,
            args.smtp_warn,
            args.smtp_crit,
            imap_time.counter,
            args.imap_warn,
            args.imap_crit,
        )

        sys.exit(returncode)

## vim:fdm=marker:ts=4:sw=4:sts=4:ai:sta:et
