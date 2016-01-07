# -*- coding: utf-8 -*-

#################################################################################################

import utils
import clientinfo
import downloadutils

#################################################################################################


class Read_EmbyServer():

    limitIndex = int(utils.settings('limitindex'))


    def __init__(self):

        self.clientInfo = clientinfo.ClientInfo()
        self.addonName = self.clientInfo.getAddonName()
        self.doUtils = downloadutils.DownloadUtils()

        self.userId = utils.window('emby_currUser')
        self.server = utils.window('emby_server%s' % self.userId)

    def logMsg(self, msg, lvl=1):

        className = self.__class__.__name__
        utils.logMsg("%s %s" % (self.addonName, className), msg, lvl)


    def split_list(self, itemlist, size):
        # Split up list in pieces of size. Will generate a list of lists
        return [itemlist[i:i+size] for i in range(0, len(itemlist), size)]

    def getItem(self, itemid):
        # This will return the full item
        item = {}

        url = "{server}/emby/Users/{UserId}/Items/%s?format=json" % itemid
        result = self.doUtils.downloadUrl(url)
        if result:
            item = result

        return item

    def getItems(self, itemlist):
        
        items = []

        itemlists = self.split_list(itemlist, 50)
        for itemlist in itemlists:
            # Will return basic information
            url = "{server}/emby/Users/{UserId}/Items?&format=json"
            params = {

                'Ids': ",".join(itemlist),
                'Fields': "Etag"
            }
            result = self.doUtils.downloadUrl(url, parameters=params)
            if result:
                items.extend(result['Items'])

        return items

    def getFullItems(self, itemlist):
        
        items = []

        itemlists = self.split_list(itemlist, 50)
        for itemlist in itemlists:

            url = "{server}/emby/Users/{UserId}/Items?format=json"
            params = {

                "Ids": ",".join(itemlist),
                "Fields": (
                        
                        "Path,Genres,SortName,Studios,Writer,ProductionYear,Taglines,"
                        "CommunityRating,OfficialRating,CumulativeRunTimeTicks,"
                        "Metascore,AirTime,DateCreated,MediaStreams,People,Overview,"
                        "CriticRating,CriticRatingSummary,Etag,ProductionLocations,"
                        "Tags,ProviderIds,RemoteTrailers,SpecialEpisodeNumbers"
                )
            }
            result = self.doUtils.downloadUrl(url, parameters=params)
            if result:
                items.extend(result['Items'])

        return items

    def getView_embyId(self, itemid):
        # Returns ancestors using embyId
        viewId = None
        url = "{server}/emby/Items/%s/Ancestors?UserId={UserId}&format=json" % itemid
        result = self.doUtils.downloadUrl(url)

        for view in result:

            viewtype = view['Type']
            if viewtype == "CollectionFolder":
                # Found view
                viewId = view['Id']

        # Compare to view table in emby database
        emby = utils.kodiSQL('emby')
        cursor_emby = emby.cursor()
        query = ' '.join((

            "SELECT view_name, media_type",
            "FROM view",
            "WHERE view_id = ?"
        ))
        cursor_emby.execute(query, (viewId,))
        result = cursor_emby.fetchone()
        try:
            viewName = result[0]
            mediatype = result[1]
        except TypeError:
            viewName = None
            mediatype = None

        cursor_emby.close()

        return [viewName, viewId, mediatype]

    def getViews(self, type, root=False):
        # Build a list of user views
        doUtils = self.doUtils
        views = []
        type = type.lower()

        if not root:
            url = "{server}/emby/Users/{UserId}/Views?format=json"
        else: # Views ungrouped
            url = "{server}/emby/Users/{UserId}/Items?Sortby=SortName&format=json"

        result = doUtils.downloadUrl(url)
        try:
            items = result['Items']
        
        except TypeError:
            self.logMsg("Error retrieving views for type: %s" % type, 2)
        
        else:
            for item in items:

                name = item['Name']
                itemId = item['Id']
                viewtype = item['Type']

                if viewtype == "Channel":
                    # Filter view types
                    continue

                # 11/10/2015 Review key, when it's added to server. Currently unavailable.
                itemtype = item.get('OriginalCollectionType', item.get('CollectionType'))

                # 11/29/2015 Remove this once OriginalCollectionType is added to stable server.
                # Assumed missing is mixed then.
                if itemtype is None:
                    url = "{server}/emby/Library/MediaFolders?format=json"
                    result = doUtils.downloadUrl(url)

                    for folder in result['Items']:
                        if itemId == folder['Id']:
                            itemtype = folder.get('CollectionType', "mixed")
                
                if (name not in ('Collections', 'Trailers') and (itemtype == type or 
                    (itemtype == "mixed" and type in ("movies", "tvshows")))):
                    
                    views.append({

                        'name': name,
                        'type': itemtype,
                        'id': itemId
                    })

        return views

    def getSection(self, parentid, itemtype=None, sortby="SortName", basic=False):
        # This is a generator, it yields as result are pulled
        # to avoid using memory to store all info
        doUtils = self.doUtils
        # Get total number of items
        url = "{server}/emby/Users/{UserId}/Items?format=json"
        params = {

            'ParentId': parentid,
            'IncludeItemTypes': itemtype,
            'CollapseBoxSetItems': False,
            'IsVirtualUnaired': False,
            'IsMissing': False,
            'Recursive': True,
            'Limit': 1
        }
        result = self.doUtils.downloadUrl(url, parameters=params)
        try:
            total = result['TotalRecordCount']
        except:
            self.logMsg("%s:%s Failed to retrieve the server response." % (url, params), 2)
            total = 0

        items = {
            
            'Items': [],
            'TotalRecordCount': total
        }
        index = 0
        jump = self.limitIndex
        while index < total:
            # Get items by chunk to increase retrieval speed at scale
            params = {

                'ParentId': parentid,
                'IncludeItemTypes': itemtype,
                'CollapseBoxSetItems': False,
                'IsVirtualUnaired': False,
                'IsMissing': False,
                'Recursive': True,
                'StartIndex': index,
                'Limit': jump,
                'SortBy': sortby,
                'SortOrder': "Ascending",
            }
            if basic:
                params['Fields'] = "Etag"
            else:
                params['Fields'] = (

                    "Path,Genres,SortName,Studios,Writer,ProductionYear,Taglines,"
                    "CommunityRating,OfficialRating,CumulativeRunTimeTicks,"
                    "Metascore,AirTime,DateCreated,MediaStreams,People,Overview,"
                    "CriticRating,CriticRatingSummary,Etag,ShortOverview,ProductionLocations,"
                    "Tags,ProviderIds,ParentId,RemoteTrailers,SpecialEpisodeNumbers"
                )
            result = doUtils.downloadUrl(url, parameters=params)
            items['Items'].extend(result['Items'])
            yield items

            del items['Items'][:]
            index += jump

    def getMovies(self, parentId, basic=False):
        # Generator
        for items in self.getSection(parentId, "Movie", basic=basic):
            yield items       
        
    def getBoxset(self):
        # Generator
        for items in self.getSection(None, "BoxSet"):
            yield items

    def getMovies_byBoxset(self, boxsetid):
        # Generator
        for items in self.getSection(boxsetid, "Movie"):
            yield items

    def getMusicVideos(self, parentId, basic=False):
        # Generator
        for items in self.getSection(parentId, "MusicVideo", basic=basic):
            yield items

    def getHomeVideos(self, parentId):
        # Generator
        for items in self.getSection(parentId, "Video"):
            yield items

    def getShows(self, parentId, basic=False):
        # Generator
        for items in self.getSection(parentId, "Series", basic=basic):
            yield items

    def getSeasons(self, showId):

        items = {
            
            'Items': [],
            'TotalRecordCount': 0
        }

        url = "{server}/emby/Shows/%s/Seasons?UserId={UserId}&format=json" % showId
        params = {

            'IsVirtualUnaired': False,
            'Fields': "Etag"
        }
        result = self.doUtils.downloadUrl(url, parameters=params)
        if result:
            items = result

        return items

    def getEpisodes(self, parentId, basic=False):
        # Generator
        for items in self.getSection(parentId, "Episode", basic=basic):
            yield items

    def getEpisodesbyShow(self, showId):
        # Generator
        for items in self.getSection(showId, "Episode"):
            yield items

    def getEpisodesbySeason(self, seasonId):
        # Generator
        for items in self.getSection(seasonId, "Episode"):
            yield items

    def getArtists(self):
        # This is a generator, it yields as result are pulled
        # to avoid using memory to store all info
        doUtils = self.doUtils
        # Get total number of items
        url = "{server}/emby/Artists?UserId={UserId}&format=json"
        params = {

            'Recursive': True,
            'Limit': 1
        }
        result = doUtils.downloadUrl(url, parameters=params)
        try:
            total = result['TotalRecordCount']
        except:
            self.logMsg("%s:%s Failed to retrieve the server response." % (url, params), 2)
            total = 0
        items = {

            'Items': [],
            'TotalRecordCount': total
        }
        index = 1
        jump = self.limitIndex

        while index < total:
            # Get items by chunk to increase retrieval speed at scale
            params = {

                'Recursive': True,
                'IsVirtualUnaired': False,
                'IsMissing': False,
                'StartIndex': index,
                'Limit': jump,
                'SortBy': "SortName",
                'SortOrder': "Ascending",
                'Fields': (

                    "Etag,Genres,SortName,Studios,Writer,ProductionYear,"
                    "CommunityRating,OfficialRating,CumulativeRunTimeTicks,Metascore,"
                    "AirTime,DateCreated,MediaStreams,People,ProviderIds,Overview"
                )
            }
            result = doUtils.downloadUrl(url, parameters=params)
            items['Items'].extend(result['Items'])
            yield items

            del items['Items'][:]
            index += jump

    def getAlbums(self, basic=False):
        # Generator
        for items in self.getSection(None, "MusicAlbum", sortby="DateCreated", basic=basic):
            yield items

    def getAlbumsbyArtist(self, artistId):
        # Generator
        for items in self.getSection(artistId, "MusicAlbum", sortby="DateCreated"):
            yield items

    def getSongs(self, basic=False):
        # Generator
        for items in self.getSection(None, "Audio", basic=basic):
            yield items

    def getSongsbyAlbum(self, albumId):
        # Generator
        for items in self.getSection(albumId, "Audio"):
            yield items

    def getAdditionalParts(self, itemId):

        items = {
            
            'Items': [],
            'TotalRecordCount': 0
        }

        url = "{server}/emby/Videos/%s/AdditionalParts?UserId={UserId}&format=json" % itemId
        result = self.doUtils.downloadUrl(url)
        if result:
            items = result

        return items

    def sortby_mediatype(self, itemids):

        sorted_items = {}

        # Sort items
        items = self.getFullItems(itemids)
        for item in items:

            mediatype = item.get('Type')
            if mediatype:
                sorted_items.setdefault(mediatype, []).append(item)

        return sorted_items
