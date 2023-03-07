import datetime
import requests
from bs4 import BeautifulSoup

import json 
import logging 
import azure.functions as func 
import sys

import pandas as pd
from newsapi import NewsApiClient
import datetime 
import re


def clean_content(content):


    logging.info("**RAW TEXT:")
    logging.info(content)

    content = content.split("You may also be interested in")[0]
    content = content.split("Related Topics")[0]
    content = content.split("Read more here")[0]
    content = content.split("Send your story ideas to")[0]

    if "This video can not be playedTo play this video you need to enable JavaScript in your browser." in content:
        content = content.split("This video can not be playedTo play this video you need to enable JavaScript in your browser.")[1]

    content = re.sub(r"Published.*?Media caption", "", content)
    content = re.sub(r"Published.*?Image caption", "", content)
    content = re.sub(r"Published.*?Image source", "", content)
    content = re.sub(r"Last updated on.*?.", "", content)
    content = re.sub(r'Last updated.*?\.', '.', content)
    content = re.sub(r"Available to UK users.*?sharingRead description", "", content)

    content = content.replace('There was an errorThis content is not available in your location', '')
    content = content.replace('To use comments you will need to have JavaScript enabled.', '')
    content = content.replace('\n"', "")
    content = content.replace('\"', "' ")
    content = content.replace('\u2026', '')

    logging.info("**PROCESSED TEXT:")
    logging.info(content)

    return content

    

def main(timer: func.TimerRequest, outputMessage: func.Out[str]) -> None: 



    utc_timestamp = datetime.datetime.utcnow().replace(
            tzinfo=datetime.timezone.utc).isoformat()

    newsapi_key = "6fdb9fb9f5154d1c8073d732a744fb9f" 
    newsapi = NewsApiClient(api_key=newsapi_key) 


    # Search for articles using the everything endpoint
    article_list = []
    articles = newsapi.get_everything(sources='bbc-news')

    # Retrieve the full content of each article using the urlToImage field
    for article in articles['articles']:
        # Make sure the article has a URL
        if 'urlToImage' in article:
            # Use the URL to fetch the full article content
            response = requests.get(article['url'])
            soup = BeautifulSoup(response.content, 'html.parser')
            try:

                # get content
                article['content'] = soup.find('article').get_text()

                # clean content
                article['content'] = clean_content(article['content'])

                article['source'] = article['source']['id']
                article = {key: value for key, value in article.items() if key in ['source', 'title', 'publishedAt', 'content']}

                if len(article['content']) > 800:
                    logging.info("**INFO : new article : %s", article['title'])
                    article_list.append(article)

            except Exception as e:
                logging.info("**INFO EXCEPTION :  : %s", e)
                pass
    
    body = json.dumps(article_list)
    outputMessage.set(body)

    logging.info('Python timer trigger function ran at %s', utc_timestamp)
