from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import urlfetch

from streamer import ContentParser, DEFAULT_HUB, Subscription, Post
import datetime
import unittest

class SubscriptionTest(unittest.TestCase):
	def setUp(self):
		subscriptions = Subscription.all()
		for subscription in subscriptions:
			subscription.delete()

	def testCanTellIfFeedIsAlreadyStored(self):
		url = "http://example.org/atom"
		f = Subscription(url=url, hub = "http://hub.example.org/", sourceUrl = "http://example.org/", key_name = url)
		f.put()
		
		self.assertTrue(Subscription.exists(url))

	def testCanTellIfFeedIsNew(self):
		url = "http://example.org/atom"
		self.assertFalse(Subscription.exists(url))

	def testAddingSubscriptionTwiceOnlyAddsOneRecordToDataStore(self):
		url = "http://example.org/atom"
		f = Subscription(url=url, hub = "http://hub.example.org/", sourceUrl = "http://example.org/", key_name = url)
		f.put()
		self.assertEquals(1, len(Subscription.find(url).fetch(1000)))
		f2 = Subscription(url=url, hub = "http://hub.example.org/", sourceUrl = "http://example.org/", key_name = url)
		f2.put()
		self.assertEquals(1, len(Subscription.find(url).fetch(1000)))
	
	def testCanDeleteSubscription(self):
		url = "http://example.org/atom"
		f = Subscription(url=url, hub = "http://hub.example.org/", sourceUrl = "http://example.org/", key_name = url)
		f.put()
		self.assertTrue(Subscription.exists(url))
		Subscription.deleteSubscriptionWithMatchingUrl(url)
		self.assertFalse(Subscription.exists(url))

class PostTest(unittest.TestCase):
	def testCanDeleteMatchingPost(self):
		feedUrl = "some feed url"
		p1 = Post(url="someurl", feedUrl = feedUrl)
		p1.put()
		
		otherFeedUrl = "other feed url"
		p2 = Post(url="someurl", feedUrl = otherFeedUrl)
		p2.put()
		
		self.assertEquals(2, len(Post.all().fetch(2)))
		Post.deleteAllPostsWithMatchingFeedUrl(feedUrl)
		self.assertEquals(1, len(Post.all().fetch(2)))
		
		allPosts = Post.all().fetch(2)
		self.assertEquals(p2.feedUrl, allPosts[0].feedUrl)
		self.assertEquals(1, len(allPosts))

class ContentParserTest(unittest.TestCase):
	SAMPLE_FEED = open("test_data/sample_entries").read()
	BLOGGER_FEED = open("test_data/blogger_feed").read()
	HUBLESS_FEED = open("test_data/hubless_feed").read()
	FEEDBURNER_FEED = open("test_data/feedburner_feed").read()
	RSS_FEED = open("test_data/rss_feed").read()
	CANONICAL_RSS_FEED = open("test_data/canonical_rss_feed").read()
	VALID_ATOM_FEED = open("test_data/valid_atom_feed").read()
	NO_AUTHOR_RSS_FEED = open("test_data/no_author_rss_feed").read()
	NO_UPDATED_ELEMENT_FEED = open("test_data/no_updated_element_feed").read()

	def testCanExtractCorrectNumberOfPostsFromFeedWithMissingUpdatedElement(self):
		parser = ContentParser(self.NO_UPDATED_ELEMENT_FEED)
		posts = parser.extractPosts()
		self.assertTrue(parser.dataValid())
		self.assertEquals(1, len(posts))

	def testCanIdentifyPostsWithGoodData(self):
		parser = ContentParser(self.SAMPLE_FEED)
		posts = parser.extractPosts()
		self.assertTrue(parser.dataValid())
	
	def testCanIdentifyPostsWithBadData(self):
		parser = ContentParser("Bad data that isn't an atom entry")
		posts = parser.extractPosts()
		self.assertFalse(parser.dataValid())
	
	def testCanExtractCorrectNumberOfPostsFromSampleFeed(self):
		parser = ContentParser(self.SAMPLE_FEED)
		posts = parser.extractPosts()
		self.assertEquals(2, len(posts))
	
	def testCanExtractPostsWithExpectedContentFromSampleFeed(self):
		parser = ContentParser(self.SAMPLE_FEED)
		posts = parser.extractPosts()
		self.assertEquals("This is the content for random item #460920825", posts[0].content)
		self.assertEquals("http://pubsubhubbub-loadtest.appspot.com/foo/460920825", posts[0].url)
		self.assertEquals("http://pubsubhubbub-loadtest.appspot.com/feed/foo", posts[0].feedUrl)
		self.assertEquals("This is the content for random item #695555168", posts[1].content)
		self.assertEquals("http://pubsubhubbub-loadtest.appspot.com/foo/695555168", posts[1].url)
		self.assertEquals("http://pubsubhubbub-loadtest.appspot.com/feed/foo", posts[1].feedUrl)

	def testCanExtractPostFromRssFeed(self):
		parser = ContentParser(self.RSS_FEED)
		posts = parser.extractPosts()
		self.assertEquals("Gnome to Split Off from GNU Project?", posts[0].title)
		self.assertEquals('<a href="http://news.ycombinator.com/item?id=991627">Comments</a>', posts[0].content)
	
	def testCanExtractMoreDataFromCanonicalRssFeed(self):
		parser = ContentParser(self.CANONICAL_RSS_FEED)
		posts = parser.extractPosts()
		self.assertEquals("RSS for BitTorrent, and other developments", posts[0].title)
		self.assertEquals("http://www.scripting.com/stories/2009/12/06/rssForBittorrentAndOtherDe.html", posts[0].url)
		self.assertEquals(datetime.datetime(*((2009, 12, 6, 23, 19, 25, 6, 340, 0)[0:6])), posts[0].datePublished)
		#TODO Find out if there's a better way to handle the RSS author element
		self.assertEquals("", posts[0].author)
	
	def testCanExtractPostsWithExpectedLinksFromBloggerFeed(self):
		parser = ContentParser(self.BLOGGER_FEED)
		posts = parser.extractPosts()
		self.assertEquals("http://blog.oshineye.com/2009/12/25-we-are-all-in-gutter-but-some-of-us.html", posts[0].url)
		self.assertEquals("http://blog.oshineye.com/2009/12/scalecamp-uk-2009.html", posts[1].url)
		self.assertEquals("http://blog.oshineye.com/2009/10/heuristic-outcomes.html", posts[2].url)
	
	def testCanExtractPostsWithExpectedAuthorNameFromBloggerFeed(self):
		parser = ContentParser(self.BLOGGER_FEED)
		posts = parser.extractPosts()
		self.assertEquals("Ade", posts[0].author)
	
	def testCanExtractAuthorNameFromBloggerFeed(self):
		parser = ContentParser(self.BLOGGER_FEED)
		self.assertEquals("Ade", parser.extractFeedAuthor())
	
	def testCanExtractAuthorNameFromValidAtomFeedWithNoTopLevelAuthor(self):
		parser = ContentParser(self.VALID_ATOM_FEED)
		self.assertEquals("Enrique Comba Riepenhausen", parser.extractFeedAuthor())

	def testCanExtractAuthorNameViaDublinCoreCreatorFromRssFeed(self):
		parser = ContentParser(self.NO_AUTHOR_RSS_FEED)
		self.assertEquals("Chris", parser.extractFeedAuthor())
	
	def testCanExtractHubFromFeed(self):
		parser = ContentParser(self.BLOGGER_FEED)
		hub = parser.extractHub()
		self.assertEquals("http://pubsubhubbub.appspot.com/", hub)
	
	def testCanOverrideHubForFeed(self):
		fakeDefaultHub = 'http://example.org/fake-url-for-hub'
		parser = ContentParser(self.BLOGGER_FEED, defaultHub = fakeDefaultHub)
		self.assertNotEquals(fakeDefaultHub, parser.extractHub())
		
		parser.alwaysUseDefaultHub = True
		self.assertEquals(fakeDefaultHub, parser.extractHub())
	
	def testCanExtractHubFromFeedburnerFeeds(self):
		self.assertEquals("http://pubsubhubbub.appspot.com", ContentParser(self.FEEDBURNER_FEED).extractHub())
		self.assertEquals("http://pubsubhubbub.appspot.com/", ContentParser(self.NO_UPDATED_ELEMENT_FEED).extractHub())
	
	def testCanExtractsDefaultHubForHubLessFeeds(self):
		parser = ContentParser(self.HUBLESS_FEED)
		hub = parser.extractHub()
		self.assertEquals(DEFAULT_HUB, hub)
	
	def testCanExtractFeedUrls(self):
		self.assertEquals("http://pubsubhubbub-loadtest.appspot.com/feed/foo", ContentParser(self.SAMPLE_FEED).extractFeedUrl())
		self.assertEquals("http://blog.oshineye.com/feeds/posts/default", ContentParser(self.BLOGGER_FEED).extractFeedUrl())
		self.assertEquals("http://en.wikipedia.org/w/index.php?title=Special:RecentChanges&feed=atom", ContentParser(self.HUBLESS_FEED).extractFeedUrl())
		self.assertEquals("http://feeds.feedburner.com/PlanetTw", ContentParser(self.FEEDBURNER_FEED).extractFeedUrl())
		self.assertEquals("http://news.ycombinator.com/rss", ContentParser(self.RSS_FEED).extractFeedUrl())
		self.assertEquals("http://www.scripting.com/rss", ContentParser(self.CANONICAL_RSS_FEED).extractFeedUrl())
		self.assertEquals("http://feeds.feedburner.com/ChrisParsons", ContentParser(self.NO_UPDATED_ELEMENT_FEED).extractFeedUrl())

	def testCanExtractSourceUrls(self):
		self.assertEquals("http://pubsubhubbub-loadtest.appspot.com/foo", ContentParser(self.SAMPLE_FEED).extractSourceUrl())
		self.assertEquals("http://blog.oshineye.com/", ContentParser(self.BLOGGER_FEED).extractSourceUrl())
		self.assertEquals("http://en.wikipedia.org/wiki/Special:RecentChanges", ContentParser(self.HUBLESS_FEED).extractSourceUrl())
		self.assertEquals("http://blogs.thoughtworks.com/", ContentParser(self.FEEDBURNER_FEED).extractSourceUrl())
		self.assertEquals("http://news.ycombinator.com/", ContentParser(self.RSS_FEED).extractSourceUrl())
		self.assertEquals("http://www.scripting.com/", ContentParser(self.CANONICAL_RSS_FEED).extractSourceUrl())
		self.assertEquals("http://chrismdp.github.com/", ContentParser(self.NO_UPDATED_ELEMENT_FEED).extractSourceUrl())
