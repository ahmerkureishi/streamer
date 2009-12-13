from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import deferred
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import login_required
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import urlfetch

import datetime
import urllib
import feedparser
import logging
import os
import time

# Change this for your installation
APP_NAME = "scaggregator"
SECRET_TOKEN = "SOME_SECRET_TOKEN"
ALWAYS_USE_DEFAULT_HUB = False
# This is a hub I've set up that does polling
DEFAULT_HUB = "http://pollinghub.appspot.com/"
# Use a cron job to re-subscribe to all feeds
LEASE_SECONDS = "86400" * 60 #90 days
OPEN_ACCESS = True

class Post(db.Model):
	url = db.StringProperty(required=True)
	feedUrl = db.StringProperty(required=True)
	title = db.StringProperty()
	content = db.TextProperty()
	datePublished = db.DateTimeProperty()
	author = db.StringProperty()
	
	@staticmethod
	def deleteAllPostsWithMatchingFeedUrl(url):
		"""This method cheats and only deletes the first 500 due to GAE constraints"""
		postsQuery = db.GqlQuery("SELECT __key__ from Post where feedUrl= :1", url)
		for postKey in postsQuery.fetch(500):
			db.delete(postKey)

class Subscription(db.Model):
	url = db.StringProperty(required=True)
	hub = db.StringProperty(required=True)
	sourceUrl = db.StringProperty(required=True)
	
	# Nickname of the person who added this feed to the system
	subscriber = db.StringProperty()
	# Automatically work out when a feed was added
	dateAdded = db.DateTimeProperty(auto_now_add=True)
	author = db.StringProperty()
	
	@staticmethod
	def exists(url):
		"""Return True or False to indicate if a subscription with the given url exists"""
		# This query only fetches the key because that's faster and computationally cheaper.
		query = db.GqlQuery("SELECT __key__ from Subscription where url= :1", url)
		return len(query.fetch(1)) > 0
	
	@staticmethod
	def deleteSubscriptionWithMatchingUrl(url):
		query = db.GqlQuery("SELECT __key__ from Subscription where url= :1", url)
		for key in query.fetch(1):
			db.delete(key)

class HubSubscriber(object):
	def __init__(self, url, hub):
		self.url = url
		self.hub = hub
		
	def subscribe(self):
		parameters = {"hub.callback" : "http://%s.appspot.com/posts" % APP_NAME,
					  "hub.mode" : "subscribe",
					  "hub.topic" : self.url,
					  "hub.verify" : "async", # We don't want subscriptions to block until verification happens
					  "hub.lease_seconds" : LEASE_SECONDS,
					  "hub.verify_token" : SECRET_TOKEN, #TODO Must generate a token based on some secret value
		}
		payload = urllib.urlencode(parameters)
		response = urlfetch.fetch(self.hub,
								payload=payload,
                        		method=urlfetch.POST,
                        		headers={'Content-Type': 'application/x-www-form-urlencoded'})
		logging.info("Status of subscription for feed: %s at hub: %s is: %d" % (self.url, self.hub, response.status_code))
		if response.status_code != 202:
			logging.info(response.content)

def render(out, htmlPage, templateValues = {}):
	path = os.path.join(os.path.dirname(__file__), htmlPage)
	out.write(template.render(path, templateValues))

def getAllSubscriptionsAsTemplateValues():
	# Get all the feeds
	subscriptions = db.GqlQuery('SELECT * from Subscription ORDER by url')
			
	# Render them in the template
	templateValues = { 'subscriptions' : subscriptions}
	return templateValues

def userIsAdmin():
	user = users.get_current_user()
	# Only admin users can see this page
	if OPEN_ACCESS or (user and users.is_current_user_admin()):
		return True
	return False

class AdminHandler(webapp.RequestHandler):
	def get(self):
		# Everybody can see this page
		render(self.response.out, 'admin.html')

class AdminAddSubscriptionHandler(webapp.RequestHandler):
	@login_required
	def get(self):
		# Only admin users can see this page
		if userIsAdmin():
			templateValues = getAllSubscriptionsAsTemplateValues()
			render(self.response.out, 'add_subscriptions.html', templateValues)
		else:
			self.error(404)

class AdminDeleteSubscriptionHandler(webapp.RequestHandler):
	@login_required
	def get(self):
		# Only admin users can see this page
		if userIsAdmin():
			templateValues = getAllSubscriptionsAsTemplateValues()
			render(self.response.out, 'delete_subscriptions.html', templateValues)
		else:
			self.error(404)
	def post(self):
		# Only admin users can see this page
		if userIsAdmin():
			url = self.request.get('url')
			logging.info("Url: %s" % url)
			if url:
				handleDeleteSubscription(url)
			self.redirect('/admin/deleteSubscription')
		else:
			self.error(404)

class AboutHandler(webapp.RequestHandler):
	def get(self):
		render(self.response.out, 'about.html')

# TODO work out to make the handle* functions deferred
def handleDeleteSubscription(url):
	logging.info("Deleting subscription: %s" % url)
	Post.deleteAllPostsWithMatchingFeedUrl(url)
	Subscription.deleteSubscriptionWithMatchingUrl(url)

def handleNewSubscription(url, nickname):
	logging.info("Subscription added: %s by %s" % (url, nickname))
	parser = ContentParser(None, DEFAULT_HUB, ALWAYS_USE_DEFAULT_HUB, urlToFetch = url)
	hub = parser.extractHub()
	sourceUrl = parser.extractSourceUrl()
	author = parser.extractFeedAuthor()
	
	# Store the url as a Feed
	subscription = Subscription(url=url, subscriber = nickname, hub = hub, sourceUrl = sourceUrl, author = author)
	subscription.put()
	
	# Tell the hub about the url
	hubSubscriber = HubSubscriber(url, hub)
	hubSubscriber.subscribe()
	
	# Store the current content of the feed
	posts = parser.extractPosts();
	logging.info("About to store %d new posts for subscription: %s" % (len(posts), url))
	db.put(posts)

class SubscriptionsHandler(webapp.RequestHandler):
	def get(self):
		"""Show all the resources in this collection"""
		# Render them in the template
		templateValues = getAllSubscriptionsAsTemplateValues()
		render(self.response.out, 'subscriptions.html', templateValues)
	def post(self):
		"""Create a new resource in this collection"""
		# Only admins can add new subscriptions
		if not userIsAdmin():
			self.error(404)
		
		# Extract the url from the request
		url = self.request.get('url')
		if Subscription.exists(url):
			logging.warning("Subscription already exists: %s" % url)
			#TODO Put a flash message in there to tell the user they've added a duplicate feed
			self.redirect('/subscriptions')
			return
		
		user = users.get_current_user()
		nickname = user.nickname()
		handleNewSubscription(url, nickname)
		#TODO Make this a deferred task
		#deferred.defer(handleNewSubscription, url=url, nickname=nickname)
		
		# Redirect the user via a GET
		self.redirect('/subscriptions')

class PostsHandler(webapp.RequestHandler):
	def get(self):
		"""Show all the resources in this collection"""
		# If this is a hub challenge
		if self.request.get('hub.challenge'):
			# If this is a subscription and the url is one we have in our database
			if self.request.get('hub.mode') == "subscribe" and Subscription.exists(self.request.get('hub.topic')):
				self.response.out.write(self.request.get('hub.challenge'))
				logging.info("Successfully accepted challenge for feed: %s" % self.request.get('hub.topic'))
			else:
				self.response.set_status(404)
				self.response.out.write("Challenge failed")
				logging.info("Challenge failed for feed: %s" % self.request.get('hub.topic'))
			# Once a challenge has been issued there's no point in returning anything other than challenge passed or failed
			return
		
		# Get the last N posts ordered by date
		limit = 30
		posts = db.GqlQuery('SELECT * from Post ORDER by datePublished desc LIMIT %d' % limit)
		
		# Render them in the template
		templateValues = { 'posts' : posts}
		render(self.response.out, 'posts.html', templateValues)

	def post(self):
		"""Create a new resource in this collection"""
		logging.info("New content: %s" % self.request.body)
		#TODO Extract out as much of this and move it into a deferred function
		parser = ContentParser(self.request.body, DEFAULT_HUB, ALWAYS_USE_DEFAULT_HUB)
		url = parser.extractFeedUrl()
		if not Subscription.exists(url):
			#404 chosen because the subscription doesn't exist
			self.response.set_status(404)
			self.response.out.write("We don't have a subscription for that feed: %s" % url)
			return

		parser = ContentParser(self.request.body, DEFAULT_HUB, ALWAYS_USE_DEFAULT_HUB)
		if not parser.dataValid():
			parser.logErrors()
			self.response.out.write("Bad entries: %s" % data)
			return
		else:
			posts = parser.extractPosts()
			db.put(posts)
			logging.info("Successfully added posts")
			self.response.set_status(200)
			self.response.out.write("Good entries")

class ContentParser(object):
	def __init__(self, content, defaultHub = DEFAULT_HUB, alwaysUseDefaultHub = ALWAYS_USE_DEFAULT_HUB, urlToFetch = ""):
		if urlToFetch:
			content = urlfetch.fetch(urlToFetch).content
		self.data = feedparser.parse(content)
		self.defaultHub = defaultHub
		self.alwaysUseDefaultHub = alwaysUseDefaultHub

	def dataValid(self):
		if self.data.bozo:
			return False
		else:
			return True

	def logErrors(self):
		logging.error('Bad feed data. %s: %r', self.data.bozo_exception.__class__.__name__, self.data.bozo_exception)

	def __createDateTime(self, entry):
		print entry
		if hasattr(entry, 'updated_parsed'):
			return datetime.datetime(*(entry.updated_parsed[0:6]))
		else:
			return datetime.datetime.utcnow()

	def __extractLink(self, entryOrFeed, relName):
		for link in entryOrFeed.links:
			if link['rel'] == relName:
				return str(link['href'])
		return None

	def __extractAtomPermaLink(self, entryOrFeed):
		if hasattr(entryOrFeed, 'links'):
			link = self.__extractLink(entryOrFeed, 'alternate')
			if link:
				return link
		return entryOrFeed.get('id', '')

	def __extractAuthor(self, entryOrFeed):
		print entryOrFeed
		# Get the precise name of the author if we can
		if hasattr(entryOrFeed, 'author_detail'):
			author = entryOrFeed['author_detail']['name']
		else:
			author = entryOrFeed.get('author', '')
		return author

	def __extractPost(self, entry):
		if hasattr(entry, 'content'):
			link = self.__extractAtomPermaLink(entry)
			title = entry.get('title', '')
			content = entry.content[0].value
			datePublished = self.__createDateTime(entry)
			
			author = self.__extractAuthor(entry)
		else:
			link = entry.get('link', '')
			title = entry.get('title', '')
			content = entry.get('description', '')
			datePublished = self.__createDateTime(entry)
			author = ""
		feedUrl = self.extractFeedUrl()
		return Post(url=link, feedUrl = feedUrl, title=title, content=content, datePublished=datePublished, author=author)

	def extractFeedAuthor(self):
		author = self.__extractAuthor(self.data.feed)
		if not author:
			return self.__extractAuthor(self.data.entries[0])
		return author

	def extractPosts(self):
		postsList = []
		for entry in self.data.entries:
			p = self.__extractPost(entry)
			postsList.append(p)
		return postsList

	def extractHub(self):
		if self.alwaysUseDefaultHub:
			return self.defaultHub
		
		hub = self.__extractLink(self.data.feed, 'hub')
		if hub is None:
			return self.defaultHub
		else:
			return hub
	
	def extractFeedUrl(self):
		for link in self.data.feed.links:
			if link['rel'] == 'http://schemas.google.com/g/2005#feed' or link['rel'] == 'self':
				return link['href']
		else:
			return self.data.feed.link + "rss"
	def extractSourceUrl(self):
		sourceUrl = self.__extractAtomPermaLink(self.data.feed)
		return sourceUrl
application = webapp.WSGIApplication([
('/', PostsHandler),
('/about', AboutHandler),
('/admin', AdminHandler),
('/admin/addSubscription', AdminAddSubscriptionHandler),
('/admin/deleteSubscription', AdminDeleteSubscriptionHandler),
('/posts', PostsHandler),
('/subscriptions', SubscriptionsHandler)],
  debug = True)
def main():
	run_wsgi_app(application)

if __name__ == '__main__':
	main()