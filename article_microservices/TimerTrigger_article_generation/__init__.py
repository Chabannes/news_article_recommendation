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


logging.info('NEEEEEEEEEEEEEW')


def remove_in_between(text, start_str, end_str):
    
    start_index = text.find(start_str)
    end_index = text.find(end_str, start_index)
    
    removed_substring = ''
    if start_index != -1 and end_index != -1:
        removed_substring = text[start_index:end_index + len(end_str)]
        text = text[:start_index] + text[end_index + len(end_str):]
    
    return text


def add_space_after_dot(text):
    return re.sub(r'\.(?! )', r'. ', text)


def clean_end_of_article(text):

    text = text.split("You may also be interested in")[0]
    text = text.split("Related Topics")[0]
    text = text.split("Read more here")[0]
    text = text.split("Send your story ideas to")[0]

    return text


def find_longest_substring(text, start_str, end_str_list):
    longest_substring = ''
    longest_substring_len = 0
    longest_end_str = None

    for end_str in end_str_list:
        start_index = text.find(start_str)
        end_index = text.find(end_str, start_index)

        if start_index != -1 and end_index != -1:
            substring = text[start_index+len(start_str):end_index]
            if len(substring) > longest_substring_len and len(substring) < 200:
                longest_substring = substring
                longest_substring_len = len(substring)
                longest_end_str = end_str
    
    return longest_end_str


def clean_start_of_article(text):

    try:
        longest_end_str = find_longest_substring(text, start_str='Published', end_str_list=['Media caption', 'Image caption', 'Copy link', 'NurPhoto', 'Getty Images'])
        text = remove_in_between(text, start_str='Published', end_str=longest_end_str)

    except:
        pass

    text = text.replace('Media caption, ', '')
    return text


def clean_middle_of_article(text):

    text = remove_in_between(text, start_str='Last updated on', end_str='.')
    text = remove_in_between(text, start_str='Available to UK users', end_str='sharingRead description')
    text = text.replace('There was an errorThis content is not available in your location', '')
    text = text.replace('To use comments you will need to have JavaScript enabled.', '')
    text = text.replace('\n"', " ")
    text = text.replace('\"', "' ")
    text = text.replace('\u2026', ' ')

    return text


def clean_content(text):

    logging.info("**RAW TEXT:")
    logging.info(text)

    text = clean_end_of_article(text)
    text = clean_start_of_article(text)
    text = clean_middle_of_article(text)
    text = add_space_after_dot(text)

    logging.info("**PROCESSED TEXT:")
    logging.info(text)

    return text

    

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
