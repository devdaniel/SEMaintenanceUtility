"""
Space Engineers Server Maintenance utility
By David McDonald - Started 12/07/2014

This script is to load a SpaceEngineers save and perform maintenance & cleanup tasks such as;
 - Removal of unneeded objects, multiple classifications of "unneeded"
 - Removal of empty factions & factions that don't own anything
 - Restore asteroids that no one is near (in progress)

It requires a fair chunk of RAM at times because it has to load & parse the large SE save file. Some of those get up to 100MB.
"""

import xml.etree.ElementTree as ET #Used to read the SE save files
import argparse #Used for CLI arguments
import shutil #For copying files to backups
import datetime #For backup naming

#########################################
### Functions ###########################
#########################################

#Function to decide whether to remove an object cluster
def DoIRemoveThisCluster(objectcluster, mode):
	hasgen = False
	hasbeacon = False
	haspower = False

	#print objectcluster
	for object in objectcluster:
		for block in object.find('CubeBlocks'):
			if len(block.attrib.values()) > 0: #If it has an attribute
				if block.attrib.values()[0] == "MyObjectBuilder_Reactor": #If it has the Reactor attribute
					hasgen = True #Ok, has a generator

					#Is it enabled and fueled? No matter what, if there's an item in a reactor, it's fueled. Possibility of breaking if they make it possible to put non-fuel into a reactor.
					if block.find('Enabled').text == "true" and len(block.find('Inventory').find('Items')) > 0:
						haspower = True
				#End reactor check

				if block.attrib.values()[0] == "MyObjectBuilder_BatteryBlock": #If it has the battery block attrib
					hasgen = True #Ok, has  apower generator

					#Is it enabled, not set to recharge and has a charge stored?
					if block.find('Enabled').text == 'true' and block.find('CurrentStoredPower').text != '0' and block.find('ProducerEnabled').text == "true":
						haspower = True #Battery is juicing the juices
				#End Battery check

				if block.attrib.values()[0] == "MyObjectBuilder_Beacon":
					hasbeacon = True
				#End beacon check
			#End of attrib IF
		#End of block loop
	#End of cluster loop

	if mode == "junk" and hasgen == False:
		return True #No power generator (reactor or battery) on here, kill it

	if mode == "dead" and haspower == False: #Must have power
		return True #KILL IT

	if mode == "barebeacon" and hasbeacon != True:
		return True #No beacon? Kill it

	if mode == "beacon" and haspower != True and hasbeacon != True:
		return True #No power, no beacon, kill it

	#Made it here, musn't be remove worthy
	return False

#Function to get a list of players that own at least a part of this object cluster
def GetClusterOwners(objectcluster):
	shareholders = []

	for object in objectcluster:
		for cube in object.find('CubeBlocks'):
			if cube.find('Owner') != None: #If there is an Owner tag on this block
				if not cube.find('Owner').text in shareholders: #If this owner isn't currently recorded
					shareholders.append(cube.find('Owner').text) #Add it to the list

	return shareholders

#Function to fetch what faction a playerID belongs to
def FindPlayerFaction(factiontree, playerID):
	for faction in factiontree:
		for member in faction.find('Members'):
			if member.find('PlayerId') == playerID:
				return faction #Return the node

	#Made it out here, the player musn't be part of a faction
	return None

#Function to return the XMl node for a specific node with a matching ID
#Mainly used for finding entities in SectorObjects
def FindByID(rootnode, idfieldname, idtosearchfor):
	for node in rootnode:
		if node.find(idfieldname).text == idtosearchfor:
			return node

	#If it made it out of the loop, didn't find entity
	return None

#Function to map out the entities all joined by rotors, known as a cluster
#attrib:MyObjectBuilder_MotorRotor connects to attrib:MyObjectBuilder_MotorStator, stator's having the numbers on them
#BROKEN - FIX IT LATER
def MapObjectCluster(sectorobjectsnode, objnode):
	entitymap = [objnode] #Final table of entity ID's that will be returned
	entityqueue = [objnode] #Queue list of entites to be processed

	#Add the initial entity
	entitymap.append(objnode)

	#Begin the loop!
	while len(entityqueue) > 0: #While the queue isn't empty
		ent = entityqueue.pop()

		if ent in entitymap: #If there comes a time where multiple rotors can join 2 objects together, I've got it covered
			continue

		entitymap.append(ent.find('EntityId').text)
		cubes = ent.find('CubeBlocks')
		for cube in cubes:
			if cube.find('SubtypeName') == "LargeRotor" or cube.find('SubtypeName') == "SmallRotor":
				entityqueue.append(FindByID(sectorobjectsnode, "EntityId", cube.find('EntityId').text)) #Add that entity to the list
				entitymap.append(FindByID(sectorobjectsnode, "EntityId", cube.find('EntityId').text))

	return entitymap

#Function to find out of an entity has a rotor or a stator
def HasJoint(objectcluster):
	for object in objectcluster:
		for block in object.find('CubeBlocks'):
			if len(block.attrib.values()) > 0: #If it has an attribute
				if block.attrib.values()[0] == "MyObjectBuilder_MotorRotor" or block.attrib.values()[0] == "MyObjectBuilder_MotorStator":
					return True #Entity has a joint

	#Made it out here, musn't have a joint
	return False

#Function to remove all inertia
def KillClusterInertia(objectcluster):
	for object in objectcluster:
		object.find('LinearVelocity').attrib["x"] = "0"
		object.find('LinearVelocity').attrib["z"] = "0"
		object.find('LinearVelocity').attrib["y"] = "0"

		object.find('AngularVelocity').attrib["x"] = "0"
		object.find('AngularVelocity').attrib["y"] = "0"
		object.find('AngularVelocity').attrib["z"] = "0"
#End KillClsterIntertia


#Function to loop through an object cluster and disable factories, hard or soft
def DisableFactories(objectcluster, mode):
	for object in objectcluster:
		for block in object.find('CubeBlocks'):
			if len(block.attrib.values()) > 0: #If it has an attribute
				if block.attrib.values()[0] == "MyObjectBuilder_Refinery": #Is a refinery
					if (mode == 'soft' and len(block.find('InputInventory').find('Items')) == 0) or mode == 'hard': #If the mode is 'soft' and there's nothing inside to be refined; or it's 'hard' mode to turn it off regardless
						block.find('Enabled').text = "false" #Turn it off
						print "Turning off refinery on entity: " + object.find('EntityId').text

				if block.attrib.values()[0] == "MyObjectBuilder_Assembler": #Is an assembler
					#Well aint that some shit, SE removes the 'Queue' node if there's nothing in the queue instead of leaving an empty node...
					if (mode == 'soft' and block.find('Queue') == None) or mode == 'hard': #If the mode is 'soft' and there's nothing in the queue; or it's 'hard' mode to turn it off regardless
						block.find('Enabled').text = "false" #Turn it off
						print "Turning off assembler on entity: " + object.find('EntityId').text

#Function to get members of a faction
def GetFactionMembers(factionNode):
	members = []

	for member in factionNode.find('Members'):
		members.append(member.find('PlayerId').text)

	return members

#Function to determine if the cluster is an NPC ship or not
def IsClusterAnNPC(objectcluster):
	namestofind = ["Private Sail", "Business Shipment", "Commercial Freighter", "Mining Carriage", "Mining Transport", "Mining Hauler", "Military Escort", "Military Minelayer", "Military Transporter"]

	for object in objectcluster:
		for block in object.find('CubeBlocks'):
			if len(block.attrib.values()) > 0: #If it has an attribute
				if block.attrib.values()[0] == "MyObjectBuilder_Beacon":
					if (block.find('CustomName').text in namestofind) and object.find('DampenersEnabled') != None: #If the beacon name matches one in the list and InertialDampners are off
						if object.find('DampenersEnabled').text == 'true':
							return True #Sounds like an NPC


	#Made it out here, musn't be an NPC
	return False

#Function to test if a SectorObjects node is a CubeGrid (something that a player's built)
def IsCubeGrid(objnode):
	if len(object.attrib.values()) > 0: #If it has an attrib
		if object.attrib.values()[0] == "MyObjectBuilder_CubeGrid":
			return True


	#Made it out to here' musn't be a cubegrid
	return False

#Function to clean up factions
#Empty factions are easy. Look through the xml, if the faction has no players, nuke it
#Bum factions are trickier. Look through all of the can-own objects in the world
#Take a list of what playerID owns which blocks
#If none of the members of a faction have ownership of any blocks, disband it
#You'll also need to compensate for objects removed during cleanup


#########################################
### Main ################################
#########################################

#Load up argparse
argparser = argparse.ArgumentParser(description="Utility for performing maintenance & cleanup on SE save files")
argparser.add_argument('save_path', nargs=1, help='path to the share folder')
argparser.add_argument('--skip-backup', '-B', help='skip backup up the save files', default=False, action='store_true')
argparser.add_argument('--big-backup', '-b', help='save the backups as their own files with timestamps. Can make save folder huge after a few backups', default=False, action='store_true')
argparser.add_argument('--cleanup-objects', '-c',
	help="clean up objects in the world. Junk mode removes everything without a reactor or battery, alive or not. Dead mode removes anything without an enabled & fueled reactor or enabled, non-recharging and charged battery. Beacon mode removes anything that doesn't have a beacon, or an unfinished beacon, and doesn't have an active power generator; reactor or battery (inspired by borg8401), BareBeacon is the same except it doesn't require power, just uses a beacon block to mark what you want to keep. WARNING: Due to the complexity of rotors, anything with a rotor on it won't be removed.",
	choices=['junk', 'dead', 'beacon', 'barebeacon'], metavar="MODE", default="", nargs=1)
argparser.add_argument('--cleanup-items', '-C', help="clean up free floating objects like ores and components. Doesn't do corpses, they are more complicated", default=False, action='store_true')
argparser.add_argument('--prune-players', '-p', help="removes old entries in the player list. Considered old if they don't own any blocks and either don't belong to a faction or IsDead is true.", default=False, action='store_true')
argparser.add_argument('--prune-factions', '-f', help="remove empty factions", default=False, action='store_true')
argparser.add_argument('--whatif', '-w', help="for debugging, won't do any backups and won't save changes", default=False, action='store_true')
argparser.add_argument('--disable-factories', '-d', help='to save on wasted CPU cycles, turn off factories. Soft turns off idle assemblers and empty refineries. Hard turns off assemblers and refineries regardless',
	default="",metavar="soft / hard", choices=['soft', 'hard'], nargs=1)
argparser.add_argument('--stop-movement', '-s', help="stops all CubeGrid linear and angular velocity, stopping them still. WARNING: This will affect civilian ships as well, may lead to a buildup of civilian ships as they rely on inertia to leave the sector.", default=False, action='store_true')
argparser.add_argument('--remove-npc-ships', '-n', help='removes any ship with inertial dampners turned off and have a beacon named Private Sail, Business Shipment, Commercial Freighter, Mining Carriage / Transport / Hauler and Military Escort / Minelayer / Transporter. Is a rough match but the option is there.', default=False, action='store_true')
argparser.add_argument('--ignore-joint', '-I', help="at current, the utility won't remove anything with a joint on it (e.g. motor). This restriction can be ignored but use with caution as it may leave 1-ended joints", default=False, action='store_true')
argparser.add_argument('--full-cleanup', '-F', help="a complete cleanup. Cleans Factions, Players, Items and Objects (junk mode). Also soft-disables factories and stops movement", default=False, action='store_true')

args = argparser.parse_args()

print ""

#Definition for a full cleanup
if args.full_cleanup == True:
	args.cleanup_objects = "junk"
	args.cleanup_items = True
	args.prune_players = True
	args.prune_factions = True
	args.stop_movement = True
	args.disable_factories = "soft"

#Check to see if an action has been specified
if args.cleanup_objects == "" and args.prune_factions == False and args.cleanup_items == False and args.prune_players == False and args.disable_factories == False and args.stop_movement == False and args.remove_npc_ships == False:
	print "Error: No action specified"
	argparser.print_help()
	exit()

#Attempt to load save file
args.save_path[0] = args.save_path[0].replace("\\","/")
if args.save_path[0] != "/": #Add on the trailing / if it's missing
	args.save_path[0] = args.save_path[0] + "/"

smallsavefilename = "Sandbox.sbc"
largesavefilename = "SANDBOX_0_0_0_.sbs"

smallsavefilepath = args.save_path[0] + smallsavefilename
largesavefilepath = args.save_path[0] + largesavefilename

#Save backups
if args.skip_backup == False and args.whatif == False:
	print "Saving backups..."
	if args.big_backup == True:
		timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
		smallbackupname = smallsavefilepath + ".backup" + timestamp
		largebackupname = largesavefilepath + ".backup" + timestamp
	else:
		smallbackupname = smallsavefilepath + ".backup"
		largebackupname = largesavefilepath + ".backup"

	#print "Saving: " + smallbackupname
	print "Saving smallsave backup..."
	shutil.copyfile(smallsavefilepath, smallbackupname)
	#print "Saving: " + largebackupname
	print "Saving largesave backup..."
	shutil.copyfile(largesavefilepath, largebackupname)

#Load saves
print "Loading %s..."%smallsavefilename
xmlsmallsavetree = ET.parse(smallsavefilepath)
xmlsmallsave = xmlsmallsavetree.getroot()

print "Loading %s file..."%largesavefilename
xmllargesavetree = ET.parse(largesavefilepath)
xmllargesave = xmllargesavetree.getroot()

print "Getting Started..."

#Try to find the Sector Objects node
if xmllargesave.find('SectorObjects') == None:
	print "Error: Unable to locate SectorObjects node!"
	exit()

sectorobjects = xmllargesave.find('SectorObjects')

#Init Lists
objectstoremove = []
owningplayers = []

print "Beginning SectorObject check..."
#Big loop through entity list

#Rewrote to be more dynamic and to allow treating multiple entites / objects as one (motor joins). Lets call these 'object clusters'
#Lets always treat things as a cluster. Even if it's a cluster of 1. Will need to modify functions to match
#Removing clusters this way should be safe. The big concern was that if I were to start removing mid-loop, not only
#	would my end point be changed, but so would the current position and objects would be skipped. This way,
#	as long as touching any part of the cluster reveals the entire cluster, it will never remove backwards, always forwards
i = 0
while i < len(sectorobjects):
	#---If removing an entity, DO NOT i++ !!!---
	object = sectorobjects[i]
	objectclass = object.attrib.values()[0]

	#---Process non-cubegrid stuff first---

	#Remove free floating objects
	if objectclass == "MyObjectBuilder_FloatingObject" and args.cleanup_items == True:
		print "Removing free-floating object: ",  object.find('EntityId').text
		sectorobjects.remove(object)
		continue #Next object

	#---CubeGrid Stuff---
	if IsCubeGrid(object) == True:

		#ROTORS ARE JOINED BY PROXIMITY WHEN THE SERVER STARTS
		#UNTIL YOU FIGURE OUT HOW TO CALCULATE THIS IN THE SAVE, JUST USE A SINGLE CLUSTER PER OBJECT
		# AND IGNORE PRUNING ALL OBJECTS THAT HAVE ROTORS ATTACHED TO THEM
		#objectcluster = MapObjectCluster(sectorobjects, object) #Generate the entity cluster map
		objectcluster = [object]

		#---Always process removal stuff before modify---
		#DO NOT REMOVE ANYTHING WITH A ROTOR OR STATOR unless the override is given, currently unable to map past joints

		if HasJoint(objectcluster) == False or args.ignore_joint == True:
			if args.remove_npc_ships == True and IsClusterAnNPC(objectcluster) == True:
				#print "Removing NPC entity: " + " ,".join(objectcluster)
				print "Removing NPC entity: " + object.find('EntityId').text #Just until clusters get sorted
				for o in objectcluster:
					sectorobjects.remove(o)
				continue #Next sector object

			if args.cleanup_objects != "" and objectclass == "MyObjectBuilder_CubeGrid" : #If its cleanup o'clock and it's a CubeGrid like a station or ship
				if DoIRemoveThisCluster(objectcluster, args.cleanup_objects) == True:
					#print "Removing CubeGrid entites: " + " ,".join(objectcluster)
					print "Removing CubeGrid entites: " + object.find('EntityId').text #Just until clusters get sorted
					for o in objectcluster:
						sectorobjects.remove(o)
					continue #Next sector object
		#End of If HasJoint

		#---After processing removal stuff, THEN do modify stuff---

		#Add to owner list
		for owner in GetClusterOwners(objectcluster):
			if not owner in owningplayers:
				owningplayers.append(owner)

		#Stop movement
		if args.stop_movement == True:
			KillClusterInertia(objectcluster)

		#Turn off factories
		if args.disable_factories != '':
			DisableFactories(objectcluster, args.disable_factories[0])
	#end CubeGrid if

	#Made it to the end without removing object, go to the next item
	i = i + 1

#End SectorObjects loop

#Begin player check. Must be after object check
if args.prune_players == True:
	print "Beginning player check..."

	playerlist = xmlsmallsave.find('AllPlayers')
	playerIDtoremove = []

	#This'll be slightly different because there's 2 player lists
	#First, get a list of players
	for player in playerlist:
		playerID = player.find('PlayerId').text
		if (not playerID in owningplayers) == True and (player.find('IsDead').text == 'true' or FindPlayerFaction(xmlsmallsave.find('Factions').find('Factions'), playerID) == None): #Doesn't own anything AND (isDead = True OR not in a faction)
			try: #Error handling for unicode names
				print "Marking player for removal: %s, %s"%(player.find('Name').text, playerID)
			except:
				print "Marking player for removal: %s, %s"%("<unicode name>", playerID)

			playerIDtoremove.append(playerID)

	#Remove from relevant lists
	if len(playerIDtoremove) > 0: #If there's things to do
		print "Removing marked players..."

		#AllPlayers section
		apltoremove = []
		for i in range(0, len(playerlist)):
			if playerlist[i].find('PlayerId').text in playerIDtoremove:
				apltoremove.append(i)
				print "Removing %s from All Players list"%playerlist[i].find('PlayerId').text
		apltoremove.reverse()
		for i in apltoremove:
			playerlist.remove(playerlist[i])

		#Players section. Yes, there's a second one
		pltoremove = []
		pllist = xmlsmallsave.find('Players')[0]
		for i in range(0, len(pllist)):
			if pllist[i].find('Value').find('PlayerId') in playerIDtoremove:
				print "Removing %s from Players list"%pllist[i].find('Value').find('PlayerId')
				pltoremove.append(i)
		pltoremove.reverse()
		for i in pltoremove:
			pllist.remove(pllist[i])

		#Factions
		#Loop through members of each faction.
		for faction in xmlsmallsave.find('Factions').find('Factions'):
			factionId = faction.find('FactionId').text
			memberlist = faction.find('Members')
			joinrequests = faction.find('JoinRequests')
			membertoremove = []

			#Cleanup Members
			for i in range(0, len(memberlist)):
				if memberlist[i].find('PlayerId').text in playerIDtoremove:
					print "Removing %s from faction %s"%(memberlist[i].find('PlayerId').text, factionId)
					membertoremove.append(i)
			membertoremove.reverse()
			for i in membertoremove:
				memberlist.remove(memberlist[i])

			#Cleanup Join Requests
			requesttoremove = []
			for i in range(0, len(joinrequests)):
				if joinrequests[i].find('PlayerId').text in playerIDtoremove:
					print "Removing %s from faction request list %s"%(joinrequests[i].find('PlayerId').text, factionId)
					requesttoremove.append(i)
			requesttoremove.reverse()
			for i in requesttoremove:
				joinrequests.remove(joinrequests[i])

		#Factions Players, yep another second one
		factionplayers = xmlsmallsave.find('Factions').find('Players')[0]
		fptoremove = []
		for i in range(0, len(factionplayers)):
			if factionplayers[i].find('Key').text in playerIDtoremove:
				print "Removing %s from faction player list"%factionplayers[i].find('Key').text
				fptoremove.append(i)
		fptoremove.reverse()
		for i in fptoremove:
			factionplayers.remove(factionplayers[i])
#End player pruning

#Begin checking factions. Must be after object check and player check
if args.prune_factions == True:
	print "Beginning faction check..."

	factionIDtoremove = []

	if xmlsmallsave.find('Factions') == None:
		print "Error: Unable to location the Factions node in save!"
		exit()

	#Find and mark down factions to be removed
	factionlist = xmlsmallsave.find('Factions').find('Factions')
	factionlisttoremove = []
	for i in range(0, len(factionlist)):
		if len(factionlist[i].find('Members')) == 0: #Has no members
			try: #Error handling for unicode names
				print "Marking faction for removal, no members: %s - %s"%(factionlist[i].find('Name').text, factionlist[i].find('FactionId').text)
			except:
				print "Marking faction for removal, no members: %s - %s"%("<unicode name>", factionlist[i].find('FactionId').text)

			factionIDtoremove.append(factionlist[i].find('FactionId').text)
			factionlisttoremove.append(i)

	#Remove from main faction table
	factionlisttoremove.reverse()
	for i in factionlisttoremove:
		factionlist.remove(factionlist[i])

	#Skip the FactionPlayer table. Will only remove factions that have no players, so it should never even be present in the FactionPlayers list

	#Remove from Relations table
	factionrelations = xmlsmallsave.find('Factions').find('Relations')
	factionrelationstoremove = []
	for i in range(0, len(factionrelations)):
		if (factionrelations[i].find('FactionId1').text in factionIDtoremove) or (factionrelations[i].find('FactionId2').text in factionIDtoremove):
			factionrelationstoremove.append(i)
	factionrelationstoremove.reverse()
	for i in factionrelationstoremove:
		factionrelations.remove(factionrelations[i])

	#Clean from FactionRequests
	#2 kinds, either an entire entry for the faction or another entry referring to the faction
	factionrequests = xmlsmallsave.find('Factions').find('Requests')
	requestbodytoremove = []
	for i in range(0, len(factionrequests)):
		#First, is this entry about a faction to be removed
		if factionrequests[i].find('FactionId').text in factionIDtoremove:
			requestbodytoremove.append(i)
			continue #Go to the next entry, don't bother about the individual requests

		#Second, loop through the requests that've been sent by this faction
		factionsubrequests = factionrequests[i].find('FactionRequests')
		subrequesttoremove = []
		for i in range(0, len(factionsubrequests)):
			if factionsubrequests[i].text in factionIDtoremove:
				subrequesttoremove.append(i)
		subrequesttoremove.reverse()
		for i in subrequesttoremove:
			factionsubrequests.remove(factionsubrequests[i])

	requestbodytoremove.reverse()
	for i in requestbodytoremove:
		factionrequests.remove(factionrequests[i])


#Ok, that should be all the checks, lets save it
if args.whatif == False:
	print "Saving changes..."
	xmllargesavetree.write(largesavefilepath)

	#Space Engineers freaks the fuck out if the top of the XML in the sbc file isn't juuuuuuust right
	smallsavetowrite = ET.tostring(xmlsmallsave, method="xml")
	#Replace the first line with that special tag. Couldn't figure out how to get elementtree to do it for me
	smallsavetowrite = """<?xml version="1.0"?>\n<MyObjectBuilder_Checkpoint xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">""" + smallsavetowrite[smallsavetowrite.find("\n"):]
	f = open(smallsavefilepath, 'w')
	f.write(smallsavetowrite)
	f.close()
else:
	print "Script complete. WhatIf was used, no action has been taken."
