###
# Copyright (c) 2007-2012, Andy Berdan, Alex Schumann, Henry Donnay
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

###

import supybot.conf as conf
import supybot.utils as utils
from supybot.commands import *
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.schedule as schedule
import supybot.callbacks as callbacks
from supybot import ircmsgs
from string import *
import re

import twitter
from urllib2 import URLError, HTTPError
import supybot.dbi as dbi

class snarfRecord(dbi.Record):
   __fields__ = [
       ('tweet', eval)
       ]
class snarfDB(plugins.DbiChannelDB):
    class DB(dbi.DB):
        Record = snarfRecord
        def add(self, tweet):
            record = self.Record(tweet=tweet)
            super(self.__class__, self).add(record)
        def tweets(self):
            return list(self)

SNARFDB = plugins.DB('snarf', {'flat': snarfDB})

preferred_encodings = ["UTF-8", "CP1252", "ISO-8859-1"]

def decode_irc(raw, preferred_encs = preferred_encodings):
    """Heuristic IRC charset decoder"""
    changed = False
    for enc in preferred_encs:
        try:
            res = raw.decode(enc)
            changed = True
            break
        except:
            pass
    if not changed:
        try:
            import chardet
            enc = chardet.detect(raw)['encoding']
            res = raw.decode(enc)
        except:
            res = raw.decode(enc, 'ignore')
            #enc += "+IGNORE"
    return res

class Twitter(callbacks.Plugin):
    "Use !post to post messages via the associated twitter account."
    threaded = True

    def __init__(self, irc):
        self.__parent = super(Twitter, self)
        self.__parent.__init__(irc)
        self.irc = irc
        self.mentionSince = None
        self.tweetsSince = None
        self.snarfdb = SNARFDB()
        try:
            schedule.removeEvent('Mentions')
        except KeyError:
            pass
        try:
            schedule.removeEvent('Tweets')
        except KeyError:
            pass
        t_consumer_key = self.registryValue('consumer_key')
        t_consumer_secret = self.registryValue('consumer_secret')
        t_access_key = self.registryValue('access_key')
        t_access_secret = self.registryValue('access_secret')
        self.api = twitter.Api(consumer_key=t_consumer_key, consumer_secret=t_consumer_secret, access_token_key=t_access_key, access_token_secret=t_access_secret)
        if self.registryValue('displayTweets'):
            statuses = self.api.GetUserTimeline(include_rts=True, count=1)
            if len(statuses) > 0:
                self.tweetsSince = statuses[0].id
            def tweetsCaller():
                self._tweets(irc)
            schedule.addPeriodicEvent(tweetsCaller, 300, 'Tweets')
        if self.registryValue('displayReplies'):
            statuses = self.api.GetMentions()
            if len(statuses) > 0:
                self.mentionSince = statuses[0].id
            def mentionCaller():
                self._mention(irc)
            schedule.addPeriodicEvent(mentionCaller, 300, 'Mentions')

    def _mention(self, irc):
        statuses = self.api.GetMentions(since_id=self.mentionSince)
        if len(statuses) > 0:
            self.mentionSince = statuses[0].id
            for channel in self.registryValue('channelList').split():
                comment = self.registryValue('replyAnnounceMsg')
                status_strs = []
                for status in statuses:
                    msg = (status.user.screen_name + ' -- ' + status.text).encode("UTF-8")
                    self.log.info(msg)
                    status_strs.append(msg)
                status_msgs = comment + " " + " || ".join(status_strs)
                for msg in ircutils.wrap(status_msgs, 470):
                    irc.queueMsg(ircmsgs.privmsg(channel, msg))
    
    def mentions(self, irc, msg, args, number):
        """<number>

        Displays latest <number> mentions"""
        statuses = self.api.GetMentions()
        status_strs = []
        for status in statuses[:number]:
            msg = (status.user.screen_name + ' -- ' + status.text).encode("UTF-8")
            status_strs.append(msg)
        if(len(status_strs) > 0):
            irc.reply(" || ".join(status_strs))
        else:
            irc.reply("None")
    mentions = wrap(mentions, ['positiveInt'])

    def _tweets(self, irc):
        statuses = self.api.GetUserTimeline(include_rts=True, since_id=self.tweetsSince)
        if len(statuses) > 0:
            self.tweetsSince = statuses[0].id
            for channel in self.registryValue('channelList').split():
                comment = self.registryValue('tweetAnnounceMsg')
                status_strs = []
                for status in statuses:
                    if status.retweeted_status is not None:
                        msg = (status.user.screen_name + ' -- RT @' + status.retweeted_status.user.screen_name + " " + status.retweeted_status.text).encode("UTF-8")
                    else:
                        msg = (status.user.screen_name + ' -- ' + status.text).encode("UTF-8")
                    msg = utils.web.htmlToText(msg)
                    self.log.info(msg)
                    status_strs.append(msg)
                status_msgs = comment + " " + " || ".join(status_strs)
                for msg in ircutils.wrap(status_msgs, 470):
                    irc.queueMsg(ircmsgs.privmsg(channel, msg))

    def mytweets(self, irc, msg, args, number):
        """<number>

        Displays latest <number> of tweets on one's own timeline"""
        statuses = self.api.GetUserTimeline(include_rts=True, count = number)
        status_strs = []
        for status in statuses:
            if status.retweeted_status is not None:
                msg = (status.user.screen_name + ' -- RT @' + status.retweeted_status.user.screen_name + " " + status.retweeted_status.text).encode("UTF-8")
            else:
                msg = (status.user.screen_name + ' -- ' + status.text).encode("UTF-8")
            status_strs.append(msg)
        if(len(status_strs) > 0):
            irc.reply(" || ".join(status_strs))
        else:
            irc.reply("None")
    mytweets = wrap(mytweets, ['positiveInt'])

    def listfriends(self, irc, msg, args):
        """takes no arguments

        Echoes the friends list."""
        users = self.api.GetFriends()
        irc.reply( utils.str.format("%L", [u.screen_name for u in users] ) )
    listfriends = wrap(listfriends)

    def listfollowers(self, irc, msg, args):
        """takes no arguments

        Echoes the follewers list."""
        users = self.api.GetFollowers()
        irc.reply( utils.str.format("%L", [u.screen_name for u in users] ) )
    listfollowers = wrap(listfollowers)

    def post(self, irc, msg, args, text):
        """<text>

        Posts <text> to the twitter network.
        """
        channel = msg.args[0]
        if not self.registryValue('enabled', channel):
            return
        try:
            tweet = {}
            tweet['message'] = decode_irc(text).encode("UTF-8")
            tweet['nick'] = decode_irc(msg.nick).encode("UTF-8")

            self.api.PostUpdate(self.registryValue('postTemplate') % tweet)
        except HTTPError:
            irc.reply( "HTTP Error... it may have worked..." )
        except URLError:
            irc.reply( "URL Error... it may have worked..." )
        else:
            irc.reply( self.registryValue('postConfirmation').encode("UTF-8") )
    post = wrap(post, ['text'])

    def tweets(self, irc, msg, args):
        """takes no arguments

        Echoes the friends timeline.
        """
        statuses = self.api.GetFriendsTimeline()
        status_strs = ['%s (%s)' % (s.text, s.user.screen_name) for s in statuses]

        if(status_strs):
            irc.reply(" || ".join(status_strs).encode("UTF-8"))
        else:
            irc.reply("None")
    tweets = wrap(tweets)

    def messages(self, irc, msg, args):
        """takes no arguments

        Echoes direct messages.
        """
        dms = self.api.GetDirectMessages()
        dm_strs = ['(from @%s) %s' % (m.sender_screen_name, m.text) for m in dms]
        if(dm_strs):
	    irc.reply(" || ".join(dm_strs).encode("UTF-8"))
        else:
            irc.reply("No messages");
    messages = wrap(messages)


    def doTopic(self, irc, msg):
        chan = msg.args[0]
        newTopic = msg.args[1]
        
        if self.registryValue('tweetTopicSnarf', chan):
            # Split the new topic into segments - TODO: store seperator regex in config
            newSegments = [item.strip() for item in re.split(' [-|] ', newTopic) ]
            # Get old segments from db
            oldSegments = [item.tweet.strip() for item in self.snarfdb.tweets(chan)]

            for newSegment in newSegments:
                if newSegment not in oldSegments:
                    # Add to db: TODO - trim this if it gets huge!
                    self.snarfdb.add(chan, newSegment)
                    self.api.PostUpdate( format("%s (%s)", newSegment.encode("UTF-8"), msg.nick) )

Class = Twitter
# vim:set shiftwidth=4 tabstop=4 expandtab:
