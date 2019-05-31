# small script to import the openbeerdb data to
# Redis using RediSearch

import redis
import csv
from redisearch import Client, TextField, NumericField, TagField, GeoField
# import pprint

redis_connection = {
    'host': 'localhost',
    'port': 6379
}

category = 'category'
style = 'style'
beer = 'beer'
brewery = 'brewery'

filepath = './'

catfile = filepath + 'categories.csv'
stylefile = filepath + 'styles.csv'
beerfile = filepath + 'beers.csv'
breweryfile = filepath + 'breweries.csv'
brewerygeofile = filepath + 'breweries_geocode.csv'

ftbeeridx = 'beerIdx'
ftbreweryidx = 'breweryIdx'

# function to drop indexes if they exist
# argument is a redisearch client
def clean_index(client):
    
    try:
        client.drop_index()
    except:
        print ("\tWARN: index {} does not exist".format(index))

# function to generate a document score. the indicator
# argument is used to generate a score
# (currently abv / 10)
def get_beer_doc_score(indicator):
    indicator = float(indicator) / 10
    
    # cannot have score greater than 1.0
    if indicator > 1:
        return 1.0

    return indicator

# function to take a csv file and import each line
# as a redis hash
# arguments: redis client
#            keyprefix (string)
#            csv file name (string)
def import_csv(r, keyprefix, importfile):
    header = []
    with open(importfile) as csvfile:
        reader = csv.reader(csvfile)
        keyname = ''
        header = ''
        for row in reader:

            if reader.line_num == 1:
                # column headers in the first line of the csv file.
                # we will use these for the field names in the redis hash
                header = row
                continue

            for idx, field in enumerate(row):
                if idx == 0:
                    # set the key name using the first column (id)
                    keyname = "{}:{}".format(keyprefix, field)
                    continue

                # hset each subsequent column as a field in the hash
                r.hset(keyname, header[idx], field)

# function to create the brewey redisearch index
# and add each brewery location info as a document in the index
# arguments: redis client and redisearch client on the brewery index
def import_brewery_geo(r, rsclient):

    # create the brewery redisearch index
    ftidxfields = [
        TextField('name', weight=5.0),
        TextField('address'),
        TextField('city'),
        TextField('state'),
        TextField('country'),
        GeoField('location')
    ]
    rsclient.create_index([*ftidxfields])

    with open(brewerygeofile) as geofile:
        geo = csv.reader(geofile)
        for row in geo:
            if geo.line_num == 1:
                # skip the header line
                continue

            # use the brewery id to generate the brewery key added earlier
            brewery_key = "{}:{}".format(brewery, row[1])

            # get all the data from the brewery hash
            binfo = r.hgetall(brewery_key)
            
            if not (any(binfo)):
                print ("\tERROR: Missing info for {}, skipping geo import".format(brewery_key))
                continue

            # add the brewery document to the index
            ftaddfields = {
                'name': binfo[b'name'].decode(),
                'address': binfo[b'address1'].decode(),
                'city': binfo[b'city'].decode(),
                'state': binfo[b'state'].decode(),
                'country': binfo[b'country'].decode(),
                'location': "{},{}".format(row[3], row[2])
            }
            try:
                rsclient.add_document(
                    "ftbrewery:{}".format(row[1]),
                    score=1.0,
                    **ftaddfields
                )
            except Exception as e:
                print ("\tERROR: Failed to add document for {}: {}".format(brewery_key, e))
                continue

# function to create the beer redisearch index
# and add each beer as a document to the index
# arguments: a redis client and a redisearch client on the beer index
def ftadd_beers(r, rsclient):

    # create beer index
    ftidxfields = [
        TextField('name', weight=5.0),
        TextField('brewery'),
        TagField('category'),
        TextField('style'),
        TextField('description'),
        NumericField('abv', sortable=True),
        NumericField('ibu', sortable=True)
    ]
    rsclient.create_index([*ftidxfields])

    header = []
    dontadd = 0
    with open(beerfile) as csvfile:
        beers = csv.reader(csvfile)
        for row in beers:
            docid = ''
            docscore = 1.0
            ftaddfields = {}

            if beers.line_num == 1:
                header = row
                continue

            for idx, field in enumerate(row):
                if idx == 0:
                    docid = "{}:{}".format(beer, field)
                    continue

                # idx 1 is brewery name
                if idx == 1:

                    if field == "":
                        # something is wrong with the csv, skip this line.
                        print ("\tEJECTING: {}".format(row))
                        dontadd = 1
                        break
                    bkey = "{}:{}".format(brewery, field)
                    ftaddfields['brewery'] = r.hget(bkey, 'name')

                # idx 2 is beer name
                elif idx == 2:

                    ftaddfields['name'] = field

                # idx 3 is category ID
                elif idx == 3:

                    catname = 'None'
                    if int(field) != -1:
                        # get the category key and hget the name of the category
                        ckey = "{}:{}".format(category, field)
                        catname = r.hget(ckey, 'cat_name')

                    ftaddfields['category'] = catname

                # idx 4 is style ID
                elif idx == 4:

                    stylename = 'None'

                    if int(field) != -1:
                        skey = "{}:{}".format(style, field)
                        stylename = r.hget(skey, 'style_name')
                    
                    ftaddfields['style'] = stylename

                # idx 5 is ABV
                elif idx == 5:

                    ftaddfields['abv'] = field

                    # update the document score based on ABV
                    docscore = get_beer_doc_score(field)

                # idx 6 is IBU
                elif idx == 6:

                    ftaddfields['ibu'] = field

            if dontadd:
                dontadd = 0
                continue

            # add beer document
            rsclient.add_document(docid, score=docscore, **ftaddfields)

def main():

    r = redis.StrictRedis(**redis_connection)
    rsbeer = Client(ftbeeridx, **redis_connection)
    rsbrewery = Client(ftbreweryidx, **redis_connection)
    
    for rsclient in [rsbeer, rsbrewery]:
        try:
            cinfo = rsclient.info()
        except:
            continue

    
        print("dropping index {}".format(cinfo['index_name']))
        clean_index(rsclient)
    
    print ("Importing categories...")
    import_csv(r, category, catfile)
    print ("Importing styles...")
    import_csv(r, style, stylefile)
    print ("Importing breweries...")
    import_csv(r, brewery, breweryfile)
    print ("Adding brewery geo data to RediSearch...")
    import_brewery_geo(r, rsbrewery)
    print ("Adding beer data to RediSearch...")
    ftadd_beers(r, rsbeer)
    print ("Done.")

if __name__=="__main__":
    main()
