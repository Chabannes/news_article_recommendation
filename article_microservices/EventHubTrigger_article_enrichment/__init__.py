import logging
import json
import time
import requests
import asyncio

import azure.functions as func
from gremlin_python.driver import client, serializer
from gremlin_python.driver.protocol import GremlinServerError
from gremlin_python.process.traversal import T

from gremlin_python.process.anonymous_traversal import traversal
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from sentence_transformers import SentenceTransformer, util


import nest_asyncio
nest_asyncio.apply()
import asyncio



async def get_best_tags(properties):
    tags = ['sport', 'tech', 'politics', 'entertainment', 'business']
    best_tags = []
    for tag in tags:
        if properties.get(tag) and properties[tag] <= 2:
            best_tags.append(tag)
    return best_tags



async def get_labels(text):


    headers = {
        'Authorization': 'Bearer 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',
        'Content-Type': 'application/json'
    }

    data = '{"inputs": "%s"}' % text[:512].replace('"', '\\"').replace("'", "\\'").encode('utf-8', 'replace')
    url = 'https://api-inference.huggingface.co/models/abhishek/autonlp-bbc-news-classification-37229289'

    logging.info('TEXT %s', text)

    response = requests.post(url, headers=headers, data=data)

    logging.info('**RESPONSE: %s', response.text)

    t = 0
    while True and t < 10:

        response = requests.post(url, headers=headers, data=data)
        
        if response.ok:
            # Extract the list of labels and scores from the predictions
            label_scores = response.json()[0]
            
            # Sort the labels based on the scores
            sorted_labels = sorted(label_scores, key=lambda x: x['score'], reverse=True)
            
            # Create a dictionary with the ranking of each label
            rankings = {}
            for i, label in enumerate(sorted_labels):
                rankings[label['label']] = i + 1

            logging.info('**RANKINGS: %s', rankings)

            return rankings
        
        elif "currently loading" in response.text:
            estimated_time = response.json()["estimated_time"]
            logging.info("Model is currently loading, waiting for %.2f seconds before retrying", 8)
            await asyncio.sleep(8)            
            t = t + 1
        else:
            raise ValueError(f"Failed to get response from Hugging Face API: {response.text}")


    logging.info('**Error in model-tagging API call: %s', response.text)
    raise ValueError('Could not get answer model-tagging API: %s', response.text)


async def main(articles: func.EventHubEvent):

    new_articles = articles

    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    sim_threshold = 0.3

    logging.info('**INFO: number of arriving articles: %s', len(new_articles))
    
    gremlin_client = None


    # Create a Gremlin client and connect to the Cosmos DB graph
    gremlin_client = client.Client('wss://cosmosdb-amavla-recommendation.gremlin.cosmos.azure.com:443/', 'g',
                                        username="/dbs/cosmosdb-amavla-recommendation/colls/graph_articles_users",
                                        password="H4WjsCs5ebeXj8j7K2lwW9ZtBLU4kZabojX2XouEuL6y55UWXwtflPQYOqSX5kUDu7vzctMmGRHrACDbFFs6og==",
                                        message_serializer=serializer.GraphSONSerializersV2d0()
                                        )


    for new_article in new_articles:
        logging.info('Python EventHub trigger processed an event: %s', new_article.get_body().decode('utf-8'))
        new_article_dict = json.loads(new_article.get_body().decode('utf-8'))

        # Check if article is already in DB
        # Define the Gremlin query to check if there is an existing article with similar title and source
        check_query_already_exist = """
                g.V().has('article', 'title', title).has('source', source)
        """

        # Execute the Gremlin query with the given article properties to check if an article already exists
        result_set = gremlin_client.submit(check_query_already_exist, {
                'title': new_article_dict['title'],
                'source': new_article_dict['source']
                            })

        # If there are no existing articles, add the new article vertex
        if not result_set.all().result():
            # Define the Gremlin query to insert the article vertex

            # Create a dictionary of properties for the new article
            properties = {
                    'title': new_article_dict['title'],
                    'content': new_article_dict['content'],
                    'source': new_article_dict['source'],
                    'publishedAt': new_article_dict['publishedAt'],
                    'partitionKey': new_article_dict['publishedAt']
            }
                

            # Add properties for each tag and its corresponding score
            label_scores = await get_labels(new_article_dict['title'])

            for tag, score in label_scores.items():
                properties[tag] = score


            # get the best tags of the new article
            best_tags = await get_best_tags(properties)

            # Construct the query to select articles with the specified properties and label
            query = "g.V().hasLabel('article')"
            for tag in best_tags:
                query += ".has('{}', lte(2))".format(tag)
            query += ".limit(200).values('title').fold()"

            # Get the same-category articles
            all_titles = gremlin_client.submit(query)
            all_titles = all_titles.all().result()
            all_titles = list(all_titles[0])

            
            # Construct the Gremlin query with the properties
            add_query = """
                    g.addV('article')
                        .property('title', title)
                        .property('content', content)
                        .property('source', source)
                        .property('publishedAt', publishedAt)
                        .property('partitionKey', partitionKey)
                    """

            # Add properties for each tag and its corresponding score to the query
            for tag, score in label_scores.items():
                add_query += f"\n.property('{tag}', {score})"

            # Execute the Gremlin query with the given article properties
            result_set = gremlin_client.submitAsync(add_query, properties)
            logging.info('**INFO: Article successfully inserted')


            # Loop over all titles in the list and compute similarity
            for title in all_titles:

                relationship_query = """
                        g.V().has('article', 'title', title1).as('a')
                            .V().has('article', 'title', title2).as('b')
                            .coalesce(
                                select('a').outE('similarity').where(inV().as('b')),
                                addE('similarity').from('a').to('b').property('value', sim)
                            )
                                        """

                # Query the content property of the article with the matching title

                query = "g.V().hasLabel('article').has('title', title).values('content').fold()"
                content = gremlin_client.submit(query, {'title': title}).all().result()
                content = list(content[0])

                embedding_new_article = model.encode(new_article_dict['content'], convert_to_tensor=True)
                embedding_article = model.encode(content, convert_to_tensor=True)
                sim = util.pytorch_cos_sim(embedding_new_article, embedding_article)[0][0].item()

                # If the similarity score is above the threshold, create a relationship between the articles
                if sim >= sim_threshold:
                    # Create a relationship between the new article and the current article
                    result_set = gremlin_client.submitAsync(relationship_query, {
                                'title1': new_article_dict['title'],
                                'title2': title,
                                'sim': sim
                        })

                    logging.info('**INFO: similarity = %s', round(sim, 2))

        else:
            logging.info('**INFO: Article is already in Database')

    # Close the Gremlin client connection
    gremlin_client.close()


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())