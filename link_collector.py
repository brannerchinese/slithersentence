#!/usr/bin/env python3
# link_collector.py
# 20130402, works.
# Run with Python 3
'''Prototype scraper for downloaded Chinese webpages.'''

import os
import sys
import urllib.request
import bs4
import time
import datetime
import sqlite3
import hashlib
import bz2
import logging

url_core = 'worldjournal'
start_url = 'http://' + url_core + '.com'

class LinkCollector(object):
    def __init__(self, logging_flag=''):
        self.initialize_state_attributes()
        self.set_up_logger(logging_flag)

    def set_up_logger(self, logging_flag):
        '''Setting up of logger is moved to this method for neatness.'''
        # Set the logging level; standard choices: 
        # DEBUG, INFO, WARN, ERROR, CRITICAL. Our default is WARN.
        log_levels = {
                '-d': logging.DEBUG,
                '-i': logging.INFO,
                '-e': logging.ERROR,
                '-c': logging.CRITICAL}
        if logging_flag in log_levels:
            the_level = log_levels[logging_flag]
        else:
            the_level = logging.WARN
        #
        # Set the application name and logger configuration.
        # We don't want the .py extension.
        app_name = __file__.split('.')[0]
        logging.basicConfig(
                format='%(asctime)s (' + app_name + '.%(funcName)s:%(lineno)d) '
                    '%(levelname)s: %(message)s', 
                datefmt='%Y%d%m_%H:%M:%S_%Z', 
                filename=app_name+'.log',
                level=the_level)

    def initialize_state_attributes(self):
        '''Initialization of attributes is moved to this method for neatness.'''
        # Misc. class attributes
        self.soup = None
        self.cursor = None
        # Counters
        self.count_dicarded_urls = 0
        self.count_crawled_pages = 0
        self.count_downloaded_pages = 0
        self.count_no_links_found_pages = 0
        self.total_links_added = 0
        # Timers
        self.crawl_time = 0
        self.now = ''

    def summarize_run(self):
        '''Summarize the main events of this crawling run.'''
        elapsed = time.time() - self.start_time
        elapsed_str = str(datetime.timedelta(seconds=elapsed))
        indent = ' ' * 4
        print('\n\nTiming')
        print(indent + 'Time elapsed: {}.'.format(elapsed_str))
        print('Links and pages')
        print(indent + '{} links added this run.'.
                format(self.total_links_added))
        print(indent + '{} non-unique links ignored.'.
                format(self.count_dicarded_urls))
        count_prospective_pages = (self.count_crawled_pages +
                self.count_no_links_found_pages)
        if count_prospective_pages:
            percentage = round(100 * self.count_crawled_pages /
                    count_prospective_pages)
        else:
            percentage = 0
        print(indent + '{0}/{1} = ({2:d}%) pages successfully scraped for '
                'links,'.format(self.count_crawled_pages,
                    count_prospective_pages, percentage))
        print('Errors')
        print(indent + '{} pages discarded (no unique or usable links found).'.
                format(self.count_no_links_found_pages))
        with sqlite3.connect('crawl_' + url_core +
                '.db') as connection:
            cursor = connection.cursor()
            cursor = cursor.execute('''SELECT * FROM urls;''')
            print('{} unique records in database'.
                    format(len(cursor.fetchall())))
            cursor.close()

    def add_links_to_db(self, url_list, hash):
        '''Attempt to add URLs to the database.

        Assumes database is open. Assumes url_list exists.

        '''
        for url in url_list:
            # Strip irrelevant reference from URL end; always follows ?
            if url:
                url = url.split('?')[0]
                # If relative URL, add prefix
                url = self.ensure_whole_url(url)
                # insert (uniquely only) into db
                try:
                    self.cursor = self.cursor.execute(
                            '''INSERT INTO urls (url, date_url_added)
                            VALUES (?, ?)''',
                            (url, self.now) )
                    self.total_links_added += 1
                    print('.', end='')
                except Exception as e:
                    logging.error(str(e) + ' with URL = ' + url)
                    self.count_dicarded_urls += 1
                    print('|', end='')
                finally:
                    # flush output, since we have had a problem with this
                    sys.stdout.flush()
            else:
                self.count_dicarded_urls += 1

    def ensure_whole_url(self, url):
        '''Internal URLs are completed here.'''
        start_of_url = url.split(':')[0]
        if start_of_url != 'http' and start_of_url != 'https':
            whole_url = start_url + url
        else:
            whole_url = url
        return whole_url

    def get_url_from_tag(self, tag):
        '''From an <a ... href...> tag return the URL alone.'''
        try:
            link = tag.attrs['href']
            link = self.ensure_whole_url(link)
        except Exception as e:
            print('tag:', tag)
            logging.error(str(e) + ' with URL = ' + url)
        return link

    def get_hashes(self):
        '''Return list of hashes for those files not yet crawled for links.

        Assumes open database.

        '''
        self.cursor = self.cursor.execute('''SELECT hash, '''
                '''to_be_crawled_for_content '''
                '''FROM urls WHERE date_crawled_for_links IS NULL '''
                '''AND date_downloaded IS NOT NULL;''')
        db_content = self.cursor.fetchall()
        return [(i[0], i[1]) for i in db_content]

    def decompress_page(self, file_object):
        '''Decompress a saved page and return its contents.'''
        try:
            file_contents = bz2.decompress(file_object.read())
        except Exception as e:
            print('in decompress_page:', e)
            return
        self.count_downloaded_pages += 1
        return file_contents

    def crawl_for_links(self, page_contents):
        '''Generate a list of URLs from the page contents passed in.

        Also, update the database for the URL passed in, so that it
       is not crawled again.

        '''
        if not page_contents:
            # ggg note: this will eventually be logged as error
            print('The page contents have been returned empty.\n')
            return
        crawl_time_start = time.time()
        try:
            self.soup = bs4.BeautifulSoup(page_contents)
        except urllib.request.URLError as e:
            logging.error(str(e) + ' with URL = ' + url)
            self.urlerrors += 1
        self.crawl_time += time.time() - crawl_time_start
        url_list = [self.get_url_from_tag(i)
                for i in self.soup.select('a[href^="/view"]')]
        return url_list

    def process_page(self, filename, hash):
        '''Open file, decompress, crawl, add links, mark crawled in db.'''
        self.now = datetime.datetime.strftime(datetime.datetime.now(),
                '%Y-%m-%d %H:%M:%S.%f')
        url_list = []
        with open(os.path.join('CRAWLED_PAGES', filename),
                'rb') as file_object:
            page_contents = self.decompress_page(file_object)
            url_list = self.crawl_for_links(page_contents)
            if url_list:
                # Loop through this url_list and add links to db IF unique
                self.add_links_to_db(url_list, hash)
            else:
                self.count_no_links_found_pages += 1 
                # ggg we should mark this page as having no useful links so 
                # this process is not repeated.
            # In either case, mark record for this file as crawled.
            try:
                self.cursor = self.cursor.execute(
                        '''UPDATE urls
                        SET date_crawled_for_links=?
                        WHERE hash=?''',
                        (self.now, hash) )
                self.count_crawled_pages += 1
            except Exception as e:
                logging.error(str(e) + ' with hash = ' + hash)
                self.count_dicarded_urls += 1
        return len(url_list)

def main(logging_flag=''):
    link_collector = LinkCollector(logging_flag)
    link_collector.start_time = time.time()
    print('''\nWe print . for a link successfully added and | for '''
            '''failure of any kind:''')
    try:
        with sqlite3.connect('crawl_' + url_core + '.db') \
                as connection:
            link_collector.cursor = connection.cursor()
            # Get list of hashes and whether for content or not of 
            # uncrawled pages
            file_hash_list = link_collector.get_hashes()
            if file_hash_list:
                # Prepare to display real-time output
                print('\nProspective uncrawled files number {}:'.
                        format(len(file_hash_list)))
                for hash, for_content_or_not in file_hash_list:
                    if hash:
                        if for_content_or_not:
                            filler = '_'
                        else:
                            filler = '_base_page_'
                        filename = url_core + filler + hash + '.bz2'
                        links_found = link_collector.process_page(filename, 
                                hash)
                    else:
                        link_collector.count_no_links_found_pages += 1
            else:
                print('\nThere are no links to be added.')
    except Exception as e:
        logging.error(e)
    finally:
        # Even though the use of "with" is supposed to ensure closed cursors
        # and connections, after some problems with locked databases I am
        # closing both manually, just to be sure.
        link_collector.cursor.close()
        connection.close()
    #
    # Report
    link_collector.summarize_run()

if __name__ == '__main__':
    main(sys.argv[-1])
