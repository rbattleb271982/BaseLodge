PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE country (
	id INTEGER NOT NULL, 
	code VARCHAR(10) NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	is_active BOOLEAN, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (code)
);
CREATE TABLE resort (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	state VARCHAR(50) NOT NULL, 
	state_full VARCHAR(50), 
	country VARCHAR(2), 
	country_code VARCHAR(10), 
	country_name VARCHAR(100), 
	country_name_override VARCHAR(100), 
	state_code VARCHAR(50), 
	state_name VARCHAR(100), 
	brand VARCHAR(20), 
	pass_brands VARCHAR(150), 
	pass_brands_json JSON, 
	slug VARCHAR(120) NOT NULL, 
	is_active BOOLEAN, 
	is_region BOOLEAN DEFAULT 'false' NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (slug)
);
INSERT INTO resort VALUES(1,'Aspen Snowmass','CO','Colorado',NULL,'US',NULL,NULL,'CO',NULL,'Ikon',NULL,'[]','aspen-snowmass',0,0);
INSERT INTO resort VALUES(2,'Aspen Highlands','CO','Colorado',NULL,'US',NULL,NULL,'CO',NULL,'Ikon',NULL,'[]','aspen-highlands',0,0);
INSERT INTO resort VALUES(3,'Buttermilk','CO','Colorado',NULL,'US',NULL,NULL,'CO',NULL,'Ikon',NULL,'[]','buttermilk',0,0);
INSERT INTO resort VALUES(4,'Snowmass','CO','Colorado',NULL,'US',NULL,NULL,'CO',NULL,'Ikon',NULL,'[]','snowmass',0,0);
INSERT INTO resort VALUES(5,'Beaver Creek','CO','Colorado','US','US','United States',NULL,'CO','Colorado','Epic','Epic','["Epic"]','beaver-creek',1,0);
INSERT INTO resort VALUES(6,'Breckenridge','CO','Colorado','US','US','United States',NULL,'CO','Colorado','Epic','Epic','["Epic"]','breckenridge',1,0);
INSERT INTO resort VALUES(7,'Keystone','CO','Colorado','US','US','United States',NULL,'CO','Colorado','Epic','Epic','["Epic"]','keystone',1,0);
INSERT INTO resort VALUES(8,'Vail','CO','Colorado','US','US','United States',NULL,'CO','Colorado','Epic','Epic','["Epic"]','vail',1,0);
INSERT INTO resort VALUES(9,'Copper Mountain','CO','Colorado','US','US','United States',NULL,'CO','Colorado','Ikon','Ikon','["Ikon"]','copper-mountain',1,0);
INSERT INTO resort VALUES(10,'Winter Park','CO','Colorado','US','US','United States',NULL,'CO','Colorado','Ikon','Ikon','["Ikon"]','winter-park',1,0);
INSERT INTO resort VALUES(11,'Eldora','CO','Colorado','US','US','United States',NULL,'CO','Colorado','Ikon','Ikon','["Ikon"]','eldora',1,0);
INSERT INTO resort VALUES(12,'Telluride','CO','Colorado','US','US','United States',NULL,'CO','Colorado','Epic','Epic','["Epic"]','telluride',1,0);
INSERT INTO resort VALUES(13,'Monarch','CO','Colorado','US','US','United States',NULL,'CO','Colorado','None','None','["None"]','monarch',1,0);
INSERT INTO resort VALUES(14,'Sunlight','CO','Colorado','US','US','United States',NULL,'CO','Colorado','None','None','["None"]','sunlight',1,0);
INSERT INTO resort VALUES(15,'Arapahoe Basin','CO','Colorado','US','US','United States',NULL,'CO','Colorado','Ikon','Ikon','["Ikon"]','arapahoe-basin',1,0);
INSERT INTO resort VALUES(16,'Loveland','CO','Colorado','US','US','United States',NULL,'CO','Colorado','Indy','Indy','["Indy"]','loveland',1,0);
INSERT INTO resort VALUES(17,'Steamboat','CO','Colorado','US','US','United States',NULL,'CO','Colorado','Ikon','Ikon','["Ikon"]','steamboat',1,0);
INSERT INTO resort VALUES(18,'Crested Butte','CO','Colorado','US','US','United States',NULL,'CO','Colorado','Epic','Epic','["Epic"]','crested-butte',1,0);
INSERT INTO resort VALUES(19,'Purgatory','CO','Colorado','US','US','United States',NULL,'CO','Colorado','None','None','["None"]','purgatory',1,0);
INSERT INTO resort VALUES(20,'Wolf Creek','CO','Colorado','US','US','United States',NULL,'CO','Colorado','None','None','["None"]','wolf-creek',1,0);
INSERT INTO resort VALUES(21,'Ski Cooper','CO','Colorado','US','US','United States',NULL,'CO','Colorado','None','None','["None"]','ski-cooper',1,0);
INSERT INTO resort VALUES(22,'Powderhorn','CO','Colorado','US','US','United States',NULL,'CO','Colorado','None','None','["None"]','powderhorn',1,0);
INSERT INTO resort VALUES(23,'Silverton Mountain','CO','Colorado','US','US','United States',NULL,'CO','Colorado','None','None','["None"]','silverton-mountain',1,0);
INSERT INTO resort VALUES(24,'Alta','UT','Utah','US','US','United States',NULL,'UT','Utah','Ikon','Ikon','["Ikon"]','alta',1,0);
INSERT INTO resort VALUES(25,'Snowbird','UT','Utah','US','US','United States',NULL,'UT','Utah','Ikon','Ikon,Mountain Collective','["Ikon", "Mountain Collective"]','snowbird',1,0);
INSERT INTO resort VALUES(26,'Solitude','UT','Utah','US','US','United States',NULL,'UT','Utah','Ikon','Ikon','["Ikon"]','solitude',1,0);
INSERT INTO resort VALUES(27,'Brighton','UT','Utah','US','US','United States',NULL,'UT','Utah','Ikon','Ikon','["Ikon"]','brighton',1,0);
INSERT INTO resort VALUES(28,'Park City','UT','Utah','US','US','United States',NULL,'UT','Utah','Epic','Epic','["Epic"]','park-city',1,0);
INSERT INTO resort VALUES(29,'Deer Valley','UT','Utah','US','US','United States',NULL,'UT','Utah','Ikon','Ikon','["Ikon"]','deer-valley',1,0);
INSERT INTO resort VALUES(30,'Snowbasin','UT','Utah','US','US','United States',NULL,'UT','Utah','Ikon','Ikon','["Ikon"]','snowbasin',1,0);
INSERT INTO resort VALUES(31,'Powder Mountain','UT','Utah','US','US','United States',NULL,'UT','Utah','None','None','["None"]','powder-mountain',1,0);
INSERT INTO resort VALUES(32,'Brian Head','UT','Utah','US','US','United States',NULL,'UT','Utah','Indy','Indy','["Indy"]','brian-head',1,0);
INSERT INTO resort VALUES(33,'Sundance','UT','Utah','US','US','United States',NULL,'UT','Utah','None','None','["None"]','sundance',1,0);
INSERT INTO resort VALUES(34,'Nordic Valley','UT','Utah','US','US','United States',NULL,'UT','Utah','None','None','["None"]','nordic-valley',1,0);
INSERT INTO resort VALUES(35,'Cherry Peak','UT','Utah','US','US','United States',NULL,'UT','Utah','None','None','["None"]','cherry-peak',1,0);
INSERT INTO resort VALUES(36,'Eagle Point','UT','Utah','US','US','United States',NULL,'UT','Utah','None','None','["None"]','eagle-point',1,0);
INSERT INTO resort VALUES(37,'Beaver Mountain','UT','Utah','US','US','United States',NULL,'UT','Utah','None','None','["None"]','beaver-mountain',1,0);
INSERT INTO resort VALUES(38,'Palisades Tahoe','CA','California','US','US','United States',NULL,'CA','California','Ikon','Ikon','["Ikon"]','palisades-tahoe',1,0);
INSERT INTO resort VALUES(39,'Northstar','CA','California','US','US','United States',NULL,'CA','California','Epic','Epic','["Epic"]','northstar',1,0);
INSERT INTO resort VALUES(40,'Heavenly','CA','California','US','US','United States',NULL,'CA','California','Epic','Epic','["Epic"]','heavenly',1,0);
INSERT INTO resort VALUES(41,'Kirkwood','CA','California','US','US','United States',NULL,'CA','California','Epic','Epic','["Epic"]','kirkwood',1,0);
INSERT INTO resort VALUES(42,'Mammoth Mountain','CA','California','US','US','United States',NULL,'CA','California','Ikon','Ikon','["Ikon"]','mammoth-mountain',1,0);
INSERT INTO resort VALUES(43,'June Mountain','CA','California','US','US','United States',NULL,'CA','California','Ikon','Ikon','["Ikon"]','june-mountain',1,0);
INSERT INTO resort VALUES(44,'Big Bear','CA','California',NULL,'US',NULL,NULL,'CA',NULL,'Ikon',NULL,'[]','big-bear',0,0);
INSERT INTO resort VALUES(45,'Sugar Bowl','CA','California','US','US','United States',NULL,'CA','California','None','None','["None"]','sugar-bowl',1,0);
INSERT INTO resort VALUES(46,'Sierra-at-Tahoe','CA','California','US','US','United States',NULL,'CA','California','Ikon','Ikon','["Ikon"]','sierra-at-tahoe',1,0);
INSERT INTO resort VALUES(47,'Boreal','CA','California','US','US','United States',NULL,'CA','California','None','None','["None"]','boreal',1,0);
INSERT INTO resort VALUES(48,'Homewood','CA','California','US','US','United States',NULL,'CA','California','None','None','["None"]','homewood',1,0);
INSERT INTO resort VALUES(49,'Diamond Peak','NV','California','US','US','United States',NULL,'NV','Nevada','None','None','["None"]','diamond-peak',1,0);
INSERT INTO resort VALUES(50,'Mt. Rose','CA','California','US','US','United States',NULL,'CA','California','None','None','["None"]','mt-rose',1,0);
INSERT INTO resort VALUES(51,'Jackson Hole','WY','Wyoming','US','US','United States',NULL,'WY','Wyoming','Ikon','Ikon,Mountain Collective','["Ikon", "Mountain Collective"]','jackson-hole',1,0);
INSERT INTO resort VALUES(52,'Grand Targhee','WY','Wyoming','US','US','United States',NULL,'WY','Wyoming','Ikon','Ikon','["Ikon"]','grand-targhee',1,0);
INSERT INTO resort VALUES(53,'Snow King','WY','Wyoming','US','US','United States',NULL,'WY','Wyoming','None','None','["None"]','snow-king',1,0);
INSERT INTO resort VALUES(54,'Snowy Range','WY','Wyoming','US','US','United States',NULL,'WY','Wyoming','None','None','["None"]','snowy-range',1,0);
INSERT INTO resort VALUES(55,'Big Sky','MT','Montana','US','US','United States',NULL,'MT','Montana','Ikon','Ikon','["Ikon"]','big-sky',1,0);
INSERT INTO resort VALUES(56,'Whitefish Mountain','MT','Montana',NULL,'US',NULL,NULL,'MT',NULL,'Other',NULL,'[]','whitefish-mountain',0,0);
INSERT INTO resort VALUES(57,'Bridger Bowl','MT','Montana','US','US','United States',NULL,'MT','Montana','Indy','Indy','["Indy"]','bridger-bowl',1,0);
INSERT INTO resort VALUES(58,'Red Lodge Mountain','MT','Montana','US','US','United States',NULL,'MT','Montana','Indy','Indy','["Indy"]','red-lodge-mountain',1,0);
INSERT INTO resort VALUES(59,'Discovery','MT','Montana','US','US','United States',NULL,'MT','Montana','None','None','["None"]','discovery',1,0);
INSERT INTO resort VALUES(60,'Crystal Mountain','WI','Washington','US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','crystal-mountain',1,0);
INSERT INTO resort VALUES(61,'Snoqualmie','WA','Washington','US','US','United States',NULL,'WA','Washington','None','None','["None"]','snoqualmie',1,0);
INSERT INTO resort VALUES(62,'Mission Ridge','WA','Washington','US','US','United States',NULL,'WA','Washington','None','None','["None"]','mission-ridge',1,0);
INSERT INTO resort VALUES(63,'Stevens Pass','WA','Washington','US','US','United States',NULL,'WA','Washington','Epic','Epic','["Epic"]','stevens-pass',1,0);
INSERT INTO resort VALUES(64,'Mt. Baker','WA','Washington',NULL,'US',NULL,NULL,'WA',NULL,'Other',NULL,'[]','mt-baker',0,0);
INSERT INTO resort VALUES(65,'White Pass','WA','Washington','US','US','United States',NULL,'WA','Washington','None','None','["None"]','white-pass',1,0);
INSERT INTO resort VALUES(66,'49 Degrees North','WA','Washington','US','US','United States',NULL,'WA','Washington','None','None','["None"]','49-degrees-north',1,0);
INSERT INTO resort VALUES(67,'Mt. Hood Meadows','OR','Oregon','US','US','United States',NULL,'OR','Oregon','None','None','["None"]','mt-hood-meadows',1,0);
INSERT INTO resort VALUES(68,'Timberline','OR','Oregon','US','US','United States',NULL,'OR','Oregon','None','None','["None"]','timberline',1,0);
INSERT INTO resort VALUES(69,'Mt. Bachelor','OR','Oregon','US','US','United States',NULL,'OR','Oregon','None','None','["None"]','mt-bachelor',1,0);
INSERT INTO resort VALUES(70,'Anthony Lakes','OR','Oregon','US','US','United States',NULL,'OR','Oregon','None','None','["None"]','anthony-lakes',1,0);
INSERT INTO resort VALUES(71,'Mt. Ashland','OR','Oregon','US','US','United States',NULL,'OR','Oregon','None','None','["None"]','mt-ashland',1,0);
INSERT INTO resort VALUES(72,'Killington','VT','Vermont',NULL,'US',NULL,NULL,'VT',NULL,'Ikon',NULL,'[]','killington',0,0);
INSERT INTO resort VALUES(73,'Sugarbush','VT','Vermont','US','US','United States',NULL,'VT','Vermont','Ikon','Ikon,Mountain Collective','["Ikon", "Mountain Collective"]','sugarbush',1,0);
INSERT INTO resort VALUES(74,'Stowe','VT','Vermont','US','US','United States',NULL,'VT','Vermont','Epic','Epic','["Epic"]','stowe',1,0);
INSERT INTO resort VALUES(75,'Stratton','VT','Vermont','US','US','United States',NULL,'VT','Vermont','Ikon','Ikon','["Ikon"]','stratton',1,0);
INSERT INTO resort VALUES(76,'Jay Peak','VT','Vermont','US','US','United States',NULL,'VT','Vermont','Ikon','Ikon','["Ikon"]','jay-peak',1,0);
INSERT INTO resort VALUES(77,'Smugglers'' Notch','VT','Vermont','US','US','United States',NULL,'VT','Vermont','None','None','["None"]','smugglers-notch',1,0);
INSERT INTO resort VALUES(78,'Mount Snow','VT','Vermont','US','US','United States',NULL,'VT','Vermont','Epic','Epic','["Epic"]','mount-snow',1,0);
INSERT INTO resort VALUES(79,'Okemo','VT','Vermont','US','US','United States',NULL,'VT','Vermont','Epic','Epic','["Epic"]','okemo',1,0);
INSERT INTO resort VALUES(80,'Bolton Valley','VT','Vermont','US','US','United States',NULL,'VT','Vermont','None','None','["None"]','bolton-valley',1,0);
INSERT INTO resort VALUES(81,'Mad River Glen','VT','Vermont','US','US','United States',NULL,'VT','Vermont','None','None','["None"]','mad-river-glen',1,0);
INSERT INTO resort VALUES(82,'Bromley','VT','Vermont','US','US','United States',NULL,'VT','Vermont','None','None','["None"]','bromley',1,0);
INSERT INTO resort VALUES(83,'Loon Mountain','NH','New Hampshire','US','US','United States',NULL,'NH','New Hampshire','Epic','Epic','["Epic"]','loon-mountain',1,0);
INSERT INTO resort VALUES(84,'Cannon Mountain','NH','New Hampshire','US','US','United States',NULL,'NH','New Hampshire','Indy','Indy','["Indy"]','cannon-mountain',1,0);
INSERT INTO resort VALUES(85,'Waterville Valley','NH','New Hampshire','US','US','United States',NULL,'NH','New Hampshire','Ikon','Ikon','["Ikon"]','waterville-valley',1,0);
INSERT INTO resort VALUES(86,'Bretton Woods','NH','New Hampshire','US','US','United States',NULL,'NH','New Hampshire','Ikon','Ikon','["Ikon"]','bretton-woods',1,0);
INSERT INTO resort VALUES(87,'Wildcat Mountain','NH','New Hampshire',NULL,'US',NULL,NULL,'NH',NULL,'Other',NULL,'[]','wildcat-mountain',0,0);
INSERT INTO resort VALUES(88,'Cranmore','NH','New Hampshire','US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','cranmore',1,0);
INSERT INTO resort VALUES(89,'Sunday River','ME','Maine','US','US','United States',NULL,'ME','Maine','Ikon','Ikon','["Ikon"]','sunday-river',1,0);
INSERT INTO resort VALUES(90,'Sugarloaf','ME','Maine','US','US','United States',NULL,'ME','Maine','Ikon','Ikon','["Ikon"]','sugarloaf',1,0);
INSERT INTO resort VALUES(91,'Saddleback','ME','Maine','US','US','United States',NULL,'ME','Maine','Ikon','Ikon','["Ikon"]','saddleback',1,0);
INSERT INTO resort VALUES(92,'Black Mountain','ME','Maine','US','US','United States',NULL,'ME','Maine','None','None','["None"]','black-mountain',1,0);
INSERT INTO resort VALUES(93,'Shawnee Peak','ME','Maine','US','US','United States',NULL,'ME','Maine','None','None','["None"]','shawnee-peak',1,0);
INSERT INTO resort VALUES(94,'Whiteface','NY','New York','US','US','United States',NULL,'NY','New York','None','None','["None"]','whiteface',1,0);
INSERT INTO resort VALUES(95,'Gore Mountain','NY','New York','US','US','United States',NULL,'NY','New York','None','None','["None"]','gore-mountain',1,0);
INSERT INTO resort VALUES(96,'Belleayre','NY','New York','US','US','United States',NULL,'NY','New York','None','None','["None"]','belleayre',1,0);
INSERT INTO resort VALUES(97,'Hunter Mountain','NY','New York','US','US','United States',NULL,'NY','New York','Epic','Epic','["Epic"]','hunter-mountain',1,0);
INSERT INTO resort VALUES(98,'Windham Mountain','NY','New York',NULL,'US',NULL,NULL,'NY',NULL,'Epic',NULL,'[]','windham-mountain',0,0);
INSERT INTO resort VALUES(99,'Taos Ski Valley','NM','New Mexico',NULL,'US',NULL,NULL,'NM',NULL,'Ikon',NULL,'[]','taos-ski-valley',0,0);
INSERT INTO resort VALUES(100,'Ski Santa Fe','NM','New Mexico','US','US','United States',NULL,'NM','New Mexico','Indy','Indy','["Indy"]','ski-santa-fe',1,0);
INSERT INTO resort VALUES(101,'Angel Fire','NM','New Mexico','US','US','United States',NULL,'NM','New Mexico','None','None','["None"]','angel-fire',1,0);
INSERT INTO resort VALUES(102,'Red River','NM','New Mexico','US','US','United States',NULL,'NM','New Mexico','None','None','["None"]','red-river',1,0);
INSERT INTO resort VALUES(103,'Sun Valley','ID','Idaho','US','US','United States',NULL,'ID','Idaho','Ikon','Ikon,Mountain Collective','["Ikon", "Mountain Collective"]','sun-valley',1,0);
INSERT INTO resort VALUES(104,'Schweitzer','ID','Idaho','US','US','United States',NULL,'ID','Idaho','Ikon','Ikon','["Ikon"]','schweitzer',1,0);
INSERT INTO resort VALUES(105,'Bogus Basin','ID','Idaho','US','US','United States',NULL,'ID','Idaho','None','None','["None"]','bogus-basin',1,0);
INSERT INTO resort VALUES(106,'Brundage Mountain','ID','Idaho',NULL,'US',NULL,NULL,'ID',NULL,'Other',NULL,'[]','brundage-mountain',0,0);
INSERT INTO resort VALUES(107,'Tamarack','ID','Idaho','US','US','United States',NULL,'ID','Idaho','None','None','["None"]','tamarack',1,0);
INSERT INTO resort VALUES(108,'Lookout Pass','MT','Idaho','US','US','United States',NULL,'MT','Montana','Indy','Indy','["Indy"]','lookout-pass',1,0);
INSERT INTO resort VALUES(109,'Boyne Mountain','MI','Michigan','US','US','United States',NULL,'MI','Michigan','Ikon','Ikon','["Ikon"]','boyne-mountain',1,0);
INSERT INTO resort VALUES(110,'Crystal Mountain MI','MI','Michigan',NULL,'US',NULL,NULL,'MI',NULL,'Other',NULL,'[]','crystal-mountain-mi',0,0);
INSERT INTO resort VALUES(111,'Nubs Nob','MI','Michigan','US','US','United States',NULL,'MI','Michigan','None','None','["None"]','nubs-nob',1,0);
INSERT INTO resort VALUES(112,'Boyne Highlands','MI','Michigan','US','US','United States',NULL,'MI','Michigan','None','None','["None"]','boyne-highlands',1,0);
INSERT INTO resort VALUES(113,'Shanty Creek','MI','Michigan','US','US','United States',NULL,'MI','Michigan','None','None','["None"]','shanty-creek',1,0);
INSERT INTO resort VALUES(114,'Alyeska Resort','AK','Alaska',NULL,'US',NULL,NULL,'AK',NULL,'Ikon',NULL,'[]','alyeska-resort',0,0);
INSERT INTO resort VALUES(115,'Eaglecrest','AK','Alaska','US','US','United States',NULL,'AK','Alaska','None','None','["None"]','eaglecrest',1,0);
INSERT INTO resort VALUES(116,'Seven Springs','PA','Pennsylvania','US','US','United States',NULL,'PA','Pennsylvania','Epic','Epic','["Epic"]','seven-springs',1,0);
INSERT INTO resort VALUES(117,'Blue Mountain PA','PA','Pennsylvania',NULL,'US',NULL,NULL,'PA',NULL,'Other',NULL,'[]','blue-mountain-pa',0,0);
INSERT INTO resort VALUES(118,'Snowshoe','WV','West Virginia','US','US','United States',NULL,'WV','West Virginia','Ikon','Ikon','["Ikon"]','snowshoe',1,0);
INSERT INTO resort VALUES(119,'Cerro Catedral','Rio Negro',NULL,'AR','AR','Argentina',NULL,'Rio Negro','Rio Negro','None','None','["None"]','cerro-catedral',1,0);
INSERT INTO resort VALUES(120,'Chapelco','Neuquen',NULL,'AR','AR','Argentina',NULL,'Neuquen','Neuquen','None','None','["None"]','chapelco',1,0);
INSERT INTO resort VALUES(121,'Las Lenas','Mendoza',NULL,'AR','AR','Argentina',NULL,'Mendoza','Mendoza','None','None','["None"]','las-lenas',1,0);
INSERT INTO resort VALUES(122,'Ski Arlberg','Tyrol',NULL,'AT','AT','Austria',NULL,'Tyrol','Tyrol','Indy','Indy','["Indy"]','ski-arlberg',1,0);
INSERT INTO resort VALUES(123,'Zell am See–Kaprun','Salzburg',NULL,'AT','AT','Austria',NULL,'Salzburg','Salzburg','None','None','["None"]','zell-am-seekaprun',1,0);
INSERT INTO resort VALUES(124,'Mayrhofen','Tyrol',NULL,'AT','AT','Austria',NULL,'Tyrol','Tyrol','None','None','["None"]','mayrhofen',1,0);
INSERT INTO resort VALUES(125,'Saalbach-Hinterglemm','Salzburg',NULL,'AT','AT','Austria',NULL,'Salzburg','Salzburg','None','None','["None"]','saalbach-hinterglemm',1,0);
INSERT INTO resort VALUES(126,'St. Anton am Arlberg','Tyrol',NULL,'AT','AT','Austria',NULL,'Tyrol','Tyrol','Ikon','Ikon','["Ikon"]','st-anton-am-arlberg',1,0);
INSERT INTO resort VALUES(127,'Kitzbühel','Tyrol',NULL,'AT','AT','Austria',NULL,'Tyrol','Tyrol','Ikon','Ikon','["Ikon"]','kitzbuhel',1,0);
INSERT INTO resort VALUES(128,'Ischgl','Tyrol',NULL,'AT','AT','Austria',NULL,'Tyrol','Tyrol','None','None','["None"]','ischgl',1,0);
INSERT INTO resort VALUES(129,'Sölden','Tyrol',NULL,'AT','AT','Austria',NULL,'Tyrol','Tyrol','None','None','["None"]','solden',1,0);
INSERT INTO resort VALUES(130,'Perisher','New South Wales',NULL,'AU','AU','Australia',NULL,'New South Wales','New South Wales','Epic','Epic','["Epic"]','perisher',1,0);
INSERT INTO resort VALUES(131,'Thredbo','New South Wales',NULL,'AU','AU','Australia',NULL,'New South Wales','New South Wales','Ikon','Ikon','["Ikon"]','thredbo',1,0);
INSERT INTO resort VALUES(132,'Falls Creek','Victoria',NULL,'AU','AU','Australia',NULL,'Victoria','Victoria','Epic','Epic','["Epic"]','falls-creek',1,0);
INSERT INTO resort VALUES(133,'Mount Hotham','Victoria',NULL,'AU','AU','Australia',NULL,'Victoria','Victoria','Epic','Epic','["Epic"]','mount-hotham',1,0);
INSERT INTO resort VALUES(134,'Bansko','Blagoevgrad',NULL,'BG','BG','Bulgaria',NULL,'Blagoevgrad','Blagoevgrad','None','None','["None"]','bansko',1,0);
INSERT INTO resort VALUES(135,'Borovets','Sofia',NULL,'BG','BG','Bulgaria',NULL,'Sofia','Sofia','None','None','["None"]','borovets',1,0);
INSERT INTO resort VALUES(136,'Pamporovo','Smolyan',NULL,'BG','BG','Bulgaria',NULL,'Smolyan','Smolyan','None','None','["None"]','pamporovo',1,0);
INSERT INTO resort VALUES(137,'Horseshoe','ON',NULL,'CA','CA','Canada',NULL,'ON','Ontario','None','None','["None"]','horseshoe',1,0);
INSERT INTO resort VALUES(138,'Banff Sunshine Village','AB',NULL,'CA','CA','Canada',NULL,'AB','Alberta','Ikon','Ikon','["Ikon"]','banff-sunshine-village',1,0);
INSERT INTO resort VALUES(139,'Castle Mountain','AB',NULL,'CA','CA','Canada',NULL,'AB','Alberta','Indy','Indy','["Indy"]','castle-mountain',1,0);
INSERT INTO resort VALUES(140,'Marmot Basin','AB',NULL,'CA','CA','Canada',NULL,'AB','Alberta','Ikon','Ikon','["Ikon"]','marmot-basin',1,0);
INSERT INTO resort VALUES(141,'Sunshine Village','AB',NULL,'CA','CA','Canada',NULL,'AB','Alberta','Ikon','Ikon','["Ikon"]','sunshine-village',1,0);
INSERT INTO resort VALUES(142,'Apex Mountain','BC',NULL,'CA','CA','Canada',NULL,'BC','British Columbia','Indy','Indy','["Indy"]','apex-mountain',1,0);
INSERT INTO resort VALUES(143,'Cypress Mountain','BC',NULL,'CA','CA','Canada',NULL,'BC','British Columbia','Ikon','Ikon','["Ikon"]','cypress-mountain',1,0);
INSERT INTO resort VALUES(144,'Fernie Alpine Resort','BC',NULL,'CA','CA','Canada',NULL,'BC','British Columbia','Epic','Epic','["Epic"]','fernie-alpine-resort',1,0);
INSERT INTO resort VALUES(145,'Kicking Horse Mountain','BC',NULL,'CA','CA','Canada',NULL,'BC','British Columbia','Epic','Epic','["Epic"]','kicking-horse-mountain',1,0);
INSERT INTO resort VALUES(146,'Whistler Blackcomb','BC',NULL,'CA','CA','Canada',NULL,'BC','British Columbia','Epic','Epic','["Epic"]','whistler-blackcomb',1,0);
INSERT INTO resort VALUES(147,'Lake Louise','AB',NULL,'CA','CA','Canada',NULL,'AB','Alberta','Ikon','Ikon','["Ikon"]','lake-louise',1,0);
INSERT INTO resort VALUES(148,'Revelstoke','BC',NULL,'CA','CA','Canada',NULL,'BC','British Columbia','Ikon','Ikon','["Ikon"]','revelstoke',1,0);
INSERT INTO resort VALUES(149,'Panorama','BC',NULL,'CA','CA','Canada',NULL,'BC','British Columbia','Ikon','Ikon','["Ikon"]','panorama',1,0);
INSERT INTO resort VALUES(150,'SilverStar','BC',NULL,'CA','CA','Canada',NULL,'BC','British Columbia','None','None','["None"]','silverstar',1,0);
INSERT INTO resort VALUES(151,'Stoneham','QC',NULL,'CA','CA','Canada',NULL,'QC','Quebec','None','None','["None"]','stoneham',1,0);
INSERT INTO resort VALUES(152,'Sun Peaks','BC',NULL,'CA','CA','Canada',NULL,'BC','British Columbia','Ikon','Ikon','["Ikon"]','sun-peaks',1,0);
INSERT INTO resort VALUES(153,'Big White','BC',NULL,'CA','CA','Canada',NULL,'BC','British Columbia','None','None','["None"]','big-white',1,0);
INSERT INTO resort VALUES(154,'Blue Mountain','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','None','None','["None"]','blue-mountain',1,0);
INSERT INTO resort VALUES(155,'Le Massif','QC',NULL,'CA','CA','Canada',NULL,'QC','Quebec','None','None','["None"]','le-massif',1,0);
INSERT INTO resort VALUES(156,'Mount Norquay','AB',NULL,'CA','CA','Canada',NULL,'AB','Alberta','Ikon','Ikon','["Ikon"]','mount-norquay',1,0);
INSERT INTO resort VALUES(157,'Nakiska','AB',NULL,'CA','CA','Canada',NULL,'AB','Alberta','Epic','Epic','["Epic"]','nakiska',1,0);
INSERT INTO resort VALUES(158,'Mont-Sainte-Anne','QC',NULL,'CA','CA','Canada',NULL,'QC','Quebec','None','None','["None"]','mont-sainte-anne',1,0);
INSERT INTO resort VALUES(159,'Kimberley','BC',NULL,'CA','CA','Canada',NULL,'BC','British Columbia','None','None','["None"]','kimberley',1,0);
INSERT INTO resort VALUES(160,'Manning Park','BC',NULL,'CA','CA','Canada',NULL,'BC','British Columbia','None','None','["None"]','manning-park',1,0);
INSERT INTO resort VALUES(161,'Sasquatch Mountain','BC',NULL,'CA','CA','Canada',NULL,'BC','British Columbia','None','None','["None"]','sasquatch-mountain',1,0);
INSERT INTO resort VALUES(162,'Asessippi','MB',NULL,'CA','CA','Canada',NULL,'MB','Manitoba','None','None','["None"]','asessippi',1,0);
INSERT INTO resort VALUES(163,'Holiday Mountain','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','holiday-mountain',1,0);
INSERT INTO resort VALUES(164,'Marble Mountain','NL',NULL,'CA','CA','Canada',NULL,'NL','Newfoundland and Labrador','None','None','["None"]','marble-mountain',1,0);
INSERT INTO resort VALUES(165,'Ski Martock','NS',NULL,'CA','CA','Canada',NULL,'NS','Nova Scotia','None','None','["None"]','ski-martock',1,0);
INSERT INTO resort VALUES(166,'Wentworth','NS',NULL,'CA','CA','Canada',NULL,'NS','Nova Scotia','None','None','["None"]','wentworth',1,0);
INSERT INTO resort VALUES(167,'Glen Eden','ON',NULL,'CA','CA','Canada',NULL,'ON','Ontario','None','None','["None"]','glen-eden',1,0);
INSERT INTO resort VALUES(168,'Mount St. Louis Moonstone','ON',NULL,'CA','CA','Canada',NULL,'ON','Ontario','None','None','["None"]','mount-st-louis-moonstone',1,0);
INSERT INTO resort VALUES(169,'Bromont','QC',NULL,'CA','CA','Canada',NULL,'QC','Quebec','None','None','["None"]','bromont',1,0);
INSERT INTO resort VALUES(170,'Mont Orford','QC',NULL,'CA','CA','Canada',NULL,'QC','Quebec','None','None','["None"]','mont-orford',1,0);
INSERT INTO resort VALUES(171,'Table Mountain','SK',NULL,'CA','CA','Canada',NULL,'SK','Saskatchewan','None','None','["None"]','table-mountain',1,0);
INSERT INTO resort VALUES(172,'Red Mountain','BC',NULL,'CA','CA','Canada',NULL,'BC','British Columbia','Ikon','Ikon','["Ikon"]','red-mountain',1,0);
INSERT INTO resort VALUES(173,'Mount Sima','YT',NULL,'CA','CA','Canada',NULL,'YT','Yukon','None','None','["None"]','mount-sima',1,0);
INSERT INTO resort VALUES(174,'Whitewater','BC',NULL,'CA','CA','Canada',NULL,'BC','British Columbia','None','None','["None"]','whitewater',1,0);
INSERT INTO resort VALUES(175,'Mont Tremblant','QC',NULL,'CA','CA','Canada',NULL,'QC','Quebec','Ikon','Ikon','["Ikon"]','mont-tremblant',1,0);
INSERT INTO resort VALUES(176,'La Parva','Santiago Metropolitan Region',NULL,'CL','CL','Chile',NULL,'Santiago Metropolitan Region','Santiago Metropolitan Region','Ikon','Ikon','["Ikon"]','la-parva',1,0);
INSERT INTO resort VALUES(177,'Valle Nevado','Santiago Metropolitan Region',NULL,'CL','CL','Chile',NULL,'Santiago Metropolitan Region','Santiago Metropolitan Region','Ikon','Ikon','["Ikon"]','valle-nevado',1,0);
INSERT INTO resort VALUES(178,'Portillo','Valparaíso',NULL,'CL','CL','Chile',NULL,'Valparaíso','Valparaíso','Ikon','Ikon','["Ikon"]','portillo',1,0);
INSERT INTO resort VALUES(179,'Corralco','Araucanía',NULL,'CL','CL','Chile',NULL,'Araucanía','Araucanía','None','None','["None"]','corralco',1,0);
INSERT INTO resort VALUES(180,'El Colorado','Santiago Metropolitan Region',NULL,'CL','CL','Chile',NULL,'Santiago Metropolitan Region','Santiago Metropolitan Region','None','None','["None"]','el-colorado',1,0);
INSERT INTO resort VALUES(181,'Nevados de Chillán','Ñuble',NULL,'CL','CL','Chile',NULL,'Ñuble','Ñuble','None','None','["None"]','nevados-de-chillan',1,0);
INSERT INTO resort VALUES(182,'Spindleruv Mlyn','Hradec Kralove',NULL,'CZ','CZ','Czech Republic',NULL,'Hradec Kralove','Hradec Kralove','None','None','["None"]','spindleruv-mlyn',1,0);
INSERT INTO resort VALUES(183,'Pec pod Snezkou','Hradec Kralove',NULL,'CZ','CZ','Czech Republic',NULL,'Hradec Kralove','Hradec Kralove','None','None','["None"]','pec-pod-snezkou',1,0);
INSERT INTO resort VALUES(184,'Klínovec','Karlovy Vary',NULL,'CZ','CZ','Czech Republic',NULL,'Karlovy Vary','Karlovy Vary','None','None','["None"]','klinovec',1,0);
INSERT INTO resort VALUES(185,'Les Arcs','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','None','None','["None"]','les-arcs',1,0);
INSERT INTO resort VALUES(186,'La Plagne','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','None','None','["None"]','la-plagne',1,0);
INSERT INTO resort VALUES(187,'Chamonix','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','Ikon','Ikon','["Ikon"]','chamonix',1,0);
INSERT INTO resort VALUES(188,'Courchevel','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','None','None','["None"]','courchevel',1,0);
INSERT INTO resort VALUES(189,'Val d''Isère','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','Ikon','Ikon','["Ikon"]','val-d-isere',1,0);
INSERT INTO resort VALUES(190,'Auron','Provence',NULL,'FR','FR','France',NULL,'Provence','Provence','None','None','["None"]','auron',1,0);
INSERT INTO resort VALUES(191,'Les Orres','Provence',NULL,'FR','FR','France',NULL,'Provence','Provence','None','None','["None"]','les-orres',1,0);
INSERT INTO resort VALUES(192,'Isola 2000','Provence-Alpes-Côte d''Azur',NULL,'FR','FR','France',NULL,'Provence-Alpes-Côte d''Azur','Provence-Alpes-Côte d''Azur','None','None','["None"]','isola-2000',1,0);
INSERT INTO resort VALUES(193,'Valberg','Provence-Alpes-Côte d''Azur',NULL,'FR','FR','France',NULL,'Provence-Alpes-Côte d''Azur','Provence-Alpes-Côte d''Azur','None','None','["None"]','valberg',1,0);
INSERT INTO resort VALUES(194,'Pra Loup','Provence-Alpes-Côte d''Azur',NULL,'FR','FR','France',NULL,'Provence-Alpes-Côte d''Azur','Provence-Alpes-Côte d''Azur','None','None','["None"]','pra-loup',1,0);
INSERT INTO resort VALUES(195,'Le Sauze / Super Sauze','Provence-Alpes-Côte d''Azur',NULL,'FR','FR','France',NULL,'Provence-Alpes-Côte d''Azur','Provence-Alpes-Côte d''Azur','None','None','["None"]','le-sauze-super-sauze',1,0);
INSERT INTO resort VALUES(196,'Vars','Provence-Alpes-Côte d''Azur',NULL,'FR','FR','France',NULL,'Provence-Alpes-Côte d''Azur','Provence-Alpes-Côte d''Azur','None','None','["None"]','vars',1,0);
INSERT INTO resort VALUES(197,'La Norma','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','None','None','["None"]','la-norma',1,0);
INSERT INTO resort VALUES(198,'Megève','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','None','None','["None"]','megeve',1,0);
INSERT INTO resort VALUES(199,'Méribel','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','None','None','["None"]','meribel',1,0);
INSERT INTO resort VALUES(200,'Les Deux Alpes','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','None','None','["None"]','les-deux-alpes',1,0);
INSERT INTO resort VALUES(201,'Val Thorens','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','None','None','["None"]','val-thorens',1,0);
INSERT INTO resort VALUES(202,'Risoul','Provence-Alpes-Côte d''Azur',NULL,'FR','FR','France',NULL,'Provence-Alpes-Côte d''Azur','Provence-Alpes-Côte d''Azur','None','None','["None"]','risoul',1,0);
INSERT INTO resort VALUES(203,'Serre Chevalier','Provence-Alpes-Côte d''Azur',NULL,'FR','FR','France',NULL,'Provence-Alpes-Côte d''Azur','Provence-Alpes-Côte d''Azur','None','None','["None"]','serre-chevalier',1,0);
INSERT INTO resort VALUES(204,'Montgenèvre','Provence-Alpes-Côte d''Azur',NULL,'FR','FR','France',NULL,'Provence-Alpes-Côte d''Azur','Provence-Alpes-Côte d''Azur','None','None','["None"]','montgenevre',1,0);
INSERT INTO resort VALUES(205,'Val Cenis','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','None','None','["None"]','val-cenis',1,0);
INSERT INTO resort VALUES(206,'Aussois','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','None','None','["None"]','aussois',1,0);
INSERT INTO resort VALUES(207,'Bonneval-sur-Arc','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','None','None','["None"]','bonneval-sur-arc',1,0);
INSERT INTO resort VALUES(208,'La Clusaz','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','None','None','["None"]','la-clusaz',1,0);
INSERT INTO resort VALUES(209,'Le Grand-Bornand','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','None','None','["None"]','le-grand-bornand',1,0);
INSERT INTO resort VALUES(210,'Samoëns','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','None','None','["None"]','samoens',1,0);
INSERT INTO resort VALUES(211,'Les Carroz','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','None','None','["None"]','les-carroz',1,0);
INSERT INTO resort VALUES(212,'Vaujany','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','None','None','["None"]','vaujany',1,0);
INSERT INTO resort VALUES(213,'Oz-en-Oisans','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','None','None','["None"]','oz-en-oisans',1,0);
INSERT INTO resort VALUES(214,'Villard-de-Lans','Auvergne-Rhône-Alpes',NULL,'FR','FR','France',NULL,'Auvergne-Rhône-Alpes','Auvergne-Rhône-Alpes','None','None','["None"]','villard-de-lans',1,0);
INSERT INTO resort VALUES(215,'Tetnuldi – Mestia','Tetnuldi–Mestia',NULL,'GE','GE','Georgia',NULL,'Tetnuldi–Mestia','Tetnuldi–Mestia','None','None','["None"]','tetnuldi-mestia',1,0);
INSERT INTO resort VALUES(216,'Hatsvali – Mestia','Samegrelo-Zemo Svaneti',NULL,'GE','GE','Georgia',NULL,'Samegrelo-Zemo Svaneti','Samegrelo-Zemo Svaneti','None','None','["None"]','hatsvali-mestia',1,0);
INSERT INTO resort VALUES(217,'Betania','Kvemo Kartli',NULL,'GE','GE','Georgia',NULL,'Kvemo Kartli','Kvemo Kartli','None','None','["None"]','betania',1,0);
INSERT INTO resort VALUES(218,'Bachmaro','Guria',NULL,'GE','GE','Georgia',NULL,'Guria','Guria','None','None','["None"]','bachmaro',1,0);
INSERT INTO resort VALUES(219,'Gudauri','Mtskheta-Mtianeti',NULL,'GE','GE','Georgia',NULL,'Mtskheta-Mtianeti','Mtskheta-Mtianeti','None','None','["None"]','gudauri',1,0);
INSERT INTO resort VALUES(220,'Bakuriani','Samtskhe-Javakheti',NULL,'GE','GE','Georgia',NULL,'Samtskhe-Javakheti','Samtskhe-Javakheti','None','None','["None"]','bakuriani',1,0);
INSERT INTO resort VALUES(221,'Garmisch-Classic','Bavaria',NULL,'DE','DE','Germany',NULL,'Bavaria','Bavaria','None','None','["None"]','garmisch-classic',1,0);
INSERT INTO resort VALUES(222,'Zugspitze','Bavaria',NULL,'DE','DE','Germany',NULL,'Bavaria','Bavaria','None','None','["None"]','zugspitze',1,0);
INSERT INTO resort VALUES(223,'Oberstdorf','Bavaria',NULL,'DE','DE','Germany',NULL,'Bavaria','Bavaria','None','None','["None"]','oberstdorf',1,0);
INSERT INTO resort VALUES(224,'Fellhorn','Bavaria',NULL,'DE','DE','Germany',NULL,'Bavaria','Bavaria','None','None','["None"]','fellhorn',1,0);
INSERT INTO resort VALUES(225,'Kanzelwand','Bavaria',NULL,'DE','DE','Germany',NULL,'Bavaria','Bavaria','None','None','["None"]','kanzelwand',1,0);
INSERT INTO resort VALUES(226,'Nebelhorn','Bavaria',NULL,'DE','DE','Germany',NULL,'Bavaria','Bavaria','None','None','["None"]','nebelhorn',1,0);
INSERT INTO resort VALUES(227,'Hörnerbahn','Bavaria',NULL,'DE','DE','Germany',NULL,'Bavaria','Bavaria','None','None','["None"]','hornerbahn',1,0);
INSERT INTO resort VALUES(228,'Balderschwang','Bavaria',NULL,'DE','DE','Germany',NULL,'Bavaria','Bavaria','None','None','["None"]','balderschwang',1,0);
INSERT INTO resort VALUES(229,'Brauneck','Bavaria',NULL,'DE','DE','Germany',NULL,'Bavaria','Bavaria','None','None','["None"]','brauneck',1,0);
INSERT INTO resort VALUES(230,'Wallberg','Bavaria',NULL,'DE','DE','Germany',NULL,'Bavaria','Bavaria','None','None','["None"]','wallberg',1,0);
INSERT INTO resort VALUES(231,'Sudelfeld','Bavaria',NULL,'DE','DE','Germany',NULL,'Bavaria','Bavaria','None','None','["None"]','sudelfeld',1,0);
INSERT INTO resort VALUES(232,'Spitzingsee–Tegernsee','Bavaria',NULL,'DE','DE','Germany',NULL,'Bavaria','Bavaria','None','None','["None"]','spitzingseetegernsee',1,0);
INSERT INTO resort VALUES(233,'Wendelstein','Bavaria',NULL,'DE','DE','Germany',NULL,'Bavaria','Bavaria','None','None','["None"]','wendelstein',1,0);
INSERT INTO resort VALUES(234,'Berchtesgaden','Bavaria',NULL,'DE','DE','Germany',NULL,'Bavaria','Bavaria','None','None','["None"]','berchtesgaden',1,0);
INSERT INTO resort VALUES(235,'Mittenwald','Bavaria',NULL,'DE','DE','Germany',NULL,'Bavaria','Bavaria','None','None','["None"]','mittenwald',1,0);
INSERT INTO resort VALUES(236,'Reit im Winkl','Bavaria',NULL,'DE','DE','Germany',NULL,'Bavaria','Bavaria','None','None','["None"]','reit-im-winkl',1,0);
INSERT INTO resort VALUES(237,'Garmisch-Partenkirchen','Bavaria',NULL,'DE','DE','Germany',NULL,'Bavaria','Bavaria','None','None','["None"]','garmisch-partenkirchen',1,0);
INSERT INTO resort VALUES(238,'Nuuk','Western Greenland',NULL,'GL','GL','Greenland',NULL,'Western Greenland','Western Greenland','None','None','["None"]','nuuk',1,0);
INSERT INTO resort VALUES(239,'Sisimiut','Western Greenland',NULL,'GL','GL','Greenland',NULL,'Western Greenland','Western Greenland','None','None','["None"]','sisimiut',1,0);
INSERT INTO resort VALUES(240,'Kulusuk','Eastern Greenland',NULL,'GL','GL','Greenland',NULL,'Eastern Greenland','Eastern Greenland','None','None','["None"]','kulusuk',1,0);
INSERT INTO resort VALUES(241,'Bláfjöll','Iceland',NULL,'IS','IS','Iceland',NULL,'Iceland','Iceland','None','None','["None"]','blafjoll',1,0);
INSERT INTO resort VALUES(242,'Hlíoarfjall','Iceland',NULL,'IS','IS','Iceland',NULL,'Iceland','Iceland','None','None','["None"]','hlioarfjall',1,0);
INSERT INTO resort VALUES(243,'Dalvík','Iceland',NULL,'IS','IS','Iceland',NULL,'Iceland','Iceland','None','None','["None"]','dalvik',1,0);
INSERT INTO resort VALUES(244,'Siglufjorour','Iceland',NULL,'IS','IS','Iceland',NULL,'Iceland','Iceland','None','None','["None"]','siglufjorour',1,0);
INSERT INTO resort VALUES(245,'Alta Badia','Trentino-Alto Adige',NULL,'IT','IT','Italy',NULL,'Trentino-Alto Adige','Trentino-Alto Adige','Ikon','Ikon','["Ikon"]','alta-badia',1,0);
INSERT INTO resort VALUES(246,'Val Gardena','Trentino-Alto Adige',NULL,'IT','IT','Italy',NULL,'Trentino-Alto Adige','Trentino-Alto Adige','Ikon','Ikon','["Ikon"]','val-gardena',1,0);
INSERT INTO resort VALUES(247,'Pontedilegno–Tonale','Lombardy / Trentino',NULL,'IT','IT','Italy',NULL,'Lombardy / Trentino','Lombardy / Trentino','Epic','Epic','["Epic"]','pontedilegnotonale',1,0);
INSERT INTO resort VALUES(248,'Kronplatz','Trentino-Alto Adige',NULL,'IT','IT','Italy',NULL,'Trentino-Alto Adige','Trentino-Alto Adige','Ikon','Ikon','["Ikon"]','kronplatz',1,0);
INSERT INTO resort VALUES(249,'Cervinia','Aosta Valley',NULL,'IT','IT','Italy',NULL,'Aosta Valley','Aosta Valley','Ikon','Ikon','["Ikon"]','cervinia',1,0);
INSERT INTO resort VALUES(250,'Courmayeur','Aosta Valley',NULL,'IT','IT','Italy',NULL,'Aosta Valley','Aosta Valley','Ikon','Ikon','["Ikon"]','courmayeur',1,0);
INSERT INTO resort VALUES(251,'La Thuile','Aosta Valley',NULL,'IT','IT','Italy',NULL,'Aosta Valley','Aosta Valley','Ikon','Ikon','["Ikon"]','la-thuile',1,0);
INSERT INTO resort VALUES(252,'Monterosa Ski','Aosta Valley',NULL,'IT','IT','Italy',NULL,'Aosta Valley','Aosta Valley','Ikon','Ikon','["Ikon"]','monterosa-ski',1,0);
INSERT INTO resort VALUES(253,'Madonna di Campiglio','Trentino',NULL,'IT','IT','Italy',NULL,'Trentino','Trentino','Epic','Epic','["Epic"]','madonna-di-campiglio',1,0);
INSERT INTO resort VALUES(254,'Val di Fassa','Trentino',NULL,'IT','IT','Italy',NULL,'Trentino','Trentino','Ikon','Ikon','["Ikon"]','val-di-fassa',1,0);
INSERT INTO resort VALUES(255,'Val di Fiemme','Trentino',NULL,'IT','IT','Italy',NULL,'Trentino','Trentino','Ikon','Ikon','["Ikon"]','val-di-fiemme',1,0);
INSERT INTO resort VALUES(256,'Cortina d''Ampezzo','Veneto',NULL,'IT','IT','Italy',NULL,'Veneto','Veneto','Ikon','Ikon','["Ikon"]','cortina-d-ampezzo',1,0);
INSERT INTO resort VALUES(257,'Pejo','Trentino',NULL,'IT','IT','Italy',NULL,'Trentino','Trentino','None','None','["None"]','pejo',1,0);
INSERT INTO resort VALUES(258,'Pinzolo','Trentino',NULL,'IT','IT','Italy',NULL,'Trentino','Trentino','None','None','["None"]','pinzolo',1,0);
INSERT INTO resort VALUES(259,'San Martino di Castrozza','Trentino',NULL,'IT','IT','Italy',NULL,'Trentino','Trentino','None','None','["None"]','san-martino-di-castrozza',1,0);
INSERT INTO resort VALUES(260,'Arabba','Veneto',NULL,'IT','IT','Italy',NULL,'Veneto','Veneto','None','None','["None"]','arabba',1,0);
INSERT INTO resort VALUES(261,'Canazei','Trentino-Alto Adige',NULL,'IT','IT','Italy',NULL,'Trentino-Alto Adige','Trentino-Alto Adige','None','None','["None"]','canazei',1,0);
INSERT INTO resort VALUES(262,'Selva di Val Gardena','Trentino-Alto Adige',NULL,'IT','IT','Italy',NULL,'Trentino-Alto Adige','Trentino-Alto Adige','None','None','["None"]','selva-di-val-gardena',1,0);
INSERT INTO resort VALUES(263,'Dolomiti Superski','Trentino-Alto Adige',NULL,'IT','IT','Italy',NULL,'Trentino-Alto Adige','Trentino-Alto Adige','None','None','["None"]','dolomiti-superski',1,0);
INSERT INTO resort VALUES(264,'Niseko','Hokkaido',NULL,'JP','JP','Japan',NULL,'Hokkaido','Hokkaido','Ikon','Ikon','["Ikon"]','niseko',1,0);
INSERT INTO resort VALUES(265,'Rusutsu','Hokkaido',NULL,'JP','JP','Japan',NULL,'Hokkaido','Hokkaido','Ikon','Ikon','["Ikon"]','rusutsu',1,0);
INSERT INTO resort VALUES(266,'Hakuba','Nagano',NULL,'JP','JP','Japan',NULL,'Nagano','Nagano','Epic','Epic','["Epic"]','hakuba',1,0);
INSERT INTO resort VALUES(267,'Furano','Hokkaido',NULL,'JP','JP','Japan',NULL,'Hokkaido','Hokkaido','Ikon','Ikon','["Ikon"]','furano',1,0);
INSERT INTO resort VALUES(268,'Kiroro','Hokkaido',NULL,'JP','JP','Japan',NULL,'Hokkaido','Hokkaido','None','None','["None"]','kiroro',1,0);
INSERT INTO resort VALUES(269,'Sahoro','Hokkaido',NULL,'JP','JP','Japan',NULL,'Hokkaido','Hokkaido','None','None','["None"]','sahoro',1,0);
INSERT INTO resort VALUES(270,'Tomamu','Hokkaido',NULL,'JP','JP','Japan',NULL,'Hokkaido','Hokkaido','None','None','["None"]','tomamu',1,0);
INSERT INTO resort VALUES(271,'Nozawa Onsen','Nagano',NULL,'JP','JP','Japan',NULL,'Nagano','Nagano','None','None','["None"]','nozawa-onsen',1,0);
INSERT INTO resort VALUES(272,'Shiga Kogen','Nagano',NULL,'JP','JP','Japan',NULL,'Nagano','Nagano','None','None','["None"]','shiga-kogen',1,0);
INSERT INTO resort VALUES(273,'Madarao','Nagano',NULL,'JP','JP','Japan',NULL,'Nagano','Nagano','None','None','["None"]','madarao',1,0);
INSERT INTO resort VALUES(274,'Myoko Kogen','Nagano',NULL,'JP','JP','Japan',NULL,'Nagano','Nagano','None','None','["None"]','myoko-kogen',1,0);
INSERT INTO resort VALUES(275,'Naeba','Niigata',NULL,'JP','JP','Japan',NULL,'Niigata','Niigata','None','None','["None"]','naeba',1,0);
INSERT INTO resort VALUES(276,'Kagura','Niigata',NULL,'JP','JP','Japan',NULL,'Niigata','Niigata','None','None','["None"]','kagura',1,0);
INSERT INTO resort VALUES(277,'GALA Yuzawa','Niigata',NULL,'JP','JP','Japan',NULL,'Niigata','Niigata','None','None','["None"]','gala-yuzawa',1,0);
INSERT INTO resort VALUES(278,'Myoko Suginohara','Niigata',NULL,'JP','JP','Japan',NULL,'Niigata','Niigata','None','None','["None"]','myoko-suginohara',1,0);
INSERT INTO resort VALUES(279,'Appi Kogen','Iwate',NULL,'JP','JP','Japan',NULL,'Iwate','Iwate','None','None','["None"]','appi-kogen',1,0);
INSERT INTO resort VALUES(280,'Geto Kogen','Iwate',NULL,'JP','JP','Japan',NULL,'Iwate','Iwate','None','None','["None"]','geto-kogen',1,0);
INSERT INTO resort VALUES(281,'Zao Onsen','Yamagata',NULL,'JP','JP','Japan',NULL,'Yamagata','Yamagata','None','None','["None"]','zao-onsen',1,0);
INSERT INTO resort VALUES(282,'Brezovica','Kosovo',NULL,'XK','XK','Kosovo',NULL,'Kosovo','Kosovo','None','None','["None"]','brezovica',1,0);
INSERT INTO resort VALUES(283,'Boge','Kosovo',NULL,'XK','XK','Kosovo',NULL,'Kosovo','Kosovo','None','None','["None"]','boge',1,0);
INSERT INTO resort VALUES(284,'Rugova','Kosovo',NULL,'XK','XK','Kosovo',NULL,'Kosovo','Kosovo','None','None','["None"]','rugova',1,0);
INSERT INTO resort VALUES(285,'Coronet Peak','Otago',NULL,'NZ','NZ','New Zealand',NULL,'Otago','Otago','None','None','["None"]','coronet-peak',1,0);
INSERT INTO resort VALUES(286,'The Remarkables','Otago',NULL,'NZ','NZ','New Zealand',NULL,'Otago','Otago','None','None','["None"]','the-remarkables',1,0);
INSERT INTO resort VALUES(287,'Treble Cone','Otago',NULL,'NZ','NZ','New Zealand',NULL,'Otago','Otago','None','None','["None"]','treble-cone',1,0);
INSERT INTO resort VALUES(288,'Mount Hutt','Canterbury',NULL,'NZ','NZ','New Zealand',NULL,'Canterbury','Canterbury','None','None','["None"]','mount-hutt',1,0);
INSERT INTO resort VALUES(289,'Trysil','Innlandet',NULL,'NO','NO','Norway',NULL,'Innlandet','Innlandet','Epic','Epic','["Epic"]','trysil',1,0);
INSERT INTO resort VALUES(290,'Hemsedal','Viken',NULL,'NO','NO','Norway',NULL,'Viken','Viken','Epic','Epic','["Epic"]','hemsedal',1,0);
INSERT INTO resort VALUES(291,'Hafjell','Norway',NULL,'NO','NO','Norway',NULL,'Norway','Norway','Epic','Epic','["Epic"]','hafjell',1,0);
INSERT INTO resort VALUES(292,'Kvitfjell','Norway',NULL,'NO','NO','Norway',NULL,'Norway','Norway','Epic','Epic','["Epic"]','kvitfjell',1,0);
INSERT INTO resort VALUES(293,'Geilo','Norway',NULL,'NO','NO','Norway',NULL,'Norway','Norway','None','None','["None"]','geilo',1,0);
INSERT INTO resort VALUES(294,'Oppdal','Norway',NULL,'NO','NO','Norway',NULL,'Norway','Norway','None','None','["None"]','oppdal',1,0);
INSERT INTO resort VALUES(295,'Narvikfjellet','Norway',NULL,'NO','NO','Norway',NULL,'Norway','Norway','None','None','["None"]','narvikfjellet',1,0);
INSERT INTO resort VALUES(296,'Stranda','Norway',NULL,'NO','NO','Norway',NULL,'Norway','Norway','None','None','["None"]','stranda',1,0);
INSERT INTO resort VALUES(297,'Kasprowy Wierch','Lesser Poland',NULL,'PL','PL','Poland',NULL,'Lesser Poland','Lesser Poland','None','None','["None"]','kasprowy-wierch',1,0);
INSERT INTO resort VALUES(298,'Białka Tatrzańska','Lesser Poland',NULL,'PL','PL','Poland',NULL,'Lesser Poland','Lesser Poland','None','None','["None"]','biaka-tatrzanska',1,0);
INSERT INTO resort VALUES(299,'Poiana Brasov','BraSOV',NULL,'RO','RO','Romania',NULL,'BraSOV','BraSOV','None','None','["None"]','poiana-brasov',1,0);
INSERT INTO resort VALUES(300,'Sinaia','Prahova',NULL,'RO','RO','Romania',NULL,'Prahova','Prahova','None','None','["None"]','sinaia',1,0);
INSERT INTO resort VALUES(301,'Jasna','Zilina',NULL,'SK','SK','Slovakia',NULL,'Zilina','Zilina','None','None','["None"]','jasna',1,0);
INSERT INTO resort VALUES(302,'Strbske Pleso','PreSOV',NULL,'SK','SK','Slovakia',NULL,'PreSOV','PreSOV','None','None','["None"]','strbske-pleso',1,0);
INSERT INTO resort VALUES(303,'Kranjska Gora','Carniola',NULL,'SI','SI','Slovenia',NULL,'Carniola','Carniola','None','None','["None"]','kranjska-gora',1,0);
INSERT INTO resort VALUES(304,'Vogel Ski Resort','Carniola',NULL,'SI','SI','Slovenia',NULL,'Carniola','Carniola','None','None','["None"]','vogel-ski-resort',1,0);
INSERT INTO resort VALUES(305,'Mariborsko Pohorje','Styria',NULL,'SI','SI','Slovenia',NULL,'Styria','Styria','None','None','["None"]','mariborsko-pohorje',1,0);
INSERT INTO resort VALUES(306,'Formigal–Panticosa','Aragon',NULL,'ES','ES','Spain',NULL,'Aragon','Aragon','None','None','["None"]','formigalpanticosa',1,0);
INSERT INTO resort VALUES(307,'Baqueira-Beret','Catalonia',NULL,'ES','ES','Spain',NULL,'Catalonia','Catalonia','None','None','["None"]','baqueira-beret',1,0);
INSERT INTO resort VALUES(308,'Formigal','Pyrenees',NULL,'ES','ES','Spain',NULL,'Pyrenees','Pyrenees','None','None','["None"]','formigal',1,0);
INSERT INTO resort VALUES(309,'Panticosa','Pyrenees',NULL,'ES','ES','Spain',NULL,'Pyrenees','Pyrenees','None','None','["None"]','panticosa',1,0);
INSERT INTO resort VALUES(310,'Cerler','Pyrenees',NULL,'ES','ES','Spain',NULL,'Pyrenees','Pyrenees','None','None','["None"]','cerler',1,0);
INSERT INTO resort VALUES(311,'Astún','Aragon',NULL,'ES','ES','Spain',NULL,'Aragon','Aragon','None','None','["None"]','astun',1,0);
INSERT INTO resort VALUES(312,'Candanchú','Aragon',NULL,'ES','ES','Spain',NULL,'Aragon','Aragon','None','None','["None"]','candanchu',1,0);
INSERT INTO resort VALUES(313,'La Molina','Pyrenees',NULL,'ES','ES','Spain',NULL,'Pyrenees','Pyrenees','None','None','["None"]','la-molina',1,0);
INSERT INTO resort VALUES(314,'Masella','Pyrenees',NULL,'ES','ES','Spain',NULL,'Pyrenees','Pyrenees','None','None','["None"]','masella',1,0);
INSERT INTO resort VALUES(315,'Boí Taüll','Pyrenees',NULL,'ES','ES','Spain',NULL,'Pyrenees','Pyrenees','None','None','["None"]','boi-taull',1,0);
INSERT INTO resort VALUES(316,'Port Ainé','Pyrenees',NULL,'ES','ES','Spain',NULL,'Pyrenees','Pyrenees','None','None','["None"]','port-aine',1,0);
INSERT INTO resort VALUES(317,'Sierra Nevada','Andalusia',NULL,'ES','ES','Spain',NULL,'Andalusia','Andalusia','None','None','["None"]','sierra-nevada',1,0);
INSERT INTO resort VALUES(318,'Åre','Jämtland',NULL,'SE','SE','Sweden',NULL,'Jämtland','Jämtland','None','None','["None"]','are',1,0);
INSERT INTO resort VALUES(319,'Abisko','Lapland',NULL,'SE','SE','Sweden',NULL,'Lapland','Lapland','None','None','["None"]','abisko',1,0);
INSERT INTO resort VALUES(320,'Riksgransen','LapLand',NULL,'SE','SE','Sweden',NULL,'LapLand','LapLand','None','None','["None"]','riksgransen',1,0);
INSERT INTO resort VALUES(321,'Bjorkliden','LapLand',NULL,'SE','SE','Sweden',NULL,'LapLand','LapLand','None','None','["None"]','bjorkliden',1,0);
INSERT INTO resort VALUES(322,'Sälen','Dalarna',NULL,'SE','SE','Sweden',NULL,'Dalarna','Dalarna','None','None','["None"]','salen',1,0);
INSERT INTO resort VALUES(323,'Vemdalen','Jämtland',NULL,'SE','SE','Sweden',NULL,'Jämtland','Jämtland','None','None','["None"]','vemdalen',1,0);
INSERT INTO resort VALUES(324,'Andermatt–Sedrun–Disentis','Uri / Graubünden',NULL,'CH','CH','Switzerland',NULL,'Uri / Graubünden','Uri / Graubünden','Ikon','Ikon,Epic','["Ikon", "Epic"]','andermattsedrundisentis',1,0);
INSERT INTO resort VALUES(325,'Davos–Klosters','Graubünden',NULL,'CH','CH','Switzerland',NULL,'Graubünden','Graubünden','Ikon','Ikon','["Ikon"]','davosklosters',1,0);
INSERT INTO resort VALUES(326,'St. Moritz','Graubünden',NULL,'CH','CH','Switzerland',NULL,'Graubünden','Graubünden','Ikon','Ikon','["Ikon"]','st-moritz',1,0);
INSERT INTO resort VALUES(327,'Zermatt','Valais',NULL,'CH','CH','Switzerland',NULL,'Valais','Valais','Ikon','Ikon','["Ikon"]','zermatt',1,0);
INSERT INTO resort VALUES(328,'Engelberg','Obwalden',NULL,'CH','CH','Switzerland',NULL,'Obwalden','Obwalden','None','None','["None"]','engelberg',1,0);
INSERT INTO resort VALUES(329,'Crans-Montana','Valais',NULL,'CH','CH','Switzerland',NULL,'Valais','Valais','None','None','["None"]','crans-montana',1,0);
INSERT INTO resort VALUES(330,'Gstaad','Bern',NULL,'CH','CH','Switzerland',NULL,'Bern','Bern','None','None','["None"]','gstaad',1,0);
INSERT INTO resort VALUES(331,'Verbier','Valais',NULL,'CH','CH','Switzerland',NULL,'Valais','Valais','None','None','["None"]','verbier',1,0);
INSERT INTO resort VALUES(332,'Erciyes','Anatolia',NULL,'TR','TR','Turkey',NULL,'Anatolia','Anatolia','None','None','["None"]','erciyes',1,0);
INSERT INTO resort VALUES(333,'Sarıkamıs','Anatolia',NULL,'TR','TR','Turkey',NULL,'Anatolia','Anatolia','None','None','["None"]','sarkams',1,0);
INSERT INTO resort VALUES(334,'Ejder 3200','Anatolia',NULL,'TR','TR','Turkey',NULL,'Anatolia','Anatolia','None','None','["None"]','ejder-3200',1,0);
INSERT INTO resort VALUES(335,'Arizona Snowbowl','AZ',NULL,'US','US','United States',NULL,'AZ','Arizona','Ikon','Ikon','["Ikon"]','arizona-snowbowl',1,0);
INSERT INTO resort VALUES(336,'Mt. Lemmon','AZ',NULL,'US','US','United States',NULL,'AZ','Arizona','None','None','["None"]','mt-lemmon',1,0);
INSERT INTO resort VALUES(337,'China Peak','CA',NULL,'US','US','United States',NULL,'CA','California','None','None','["None"]','china-peak',1,0);
INSERT INTO resort VALUES(338,'Mt. Baldy','CA',NULL,'US','US','United States',NULL,'CA','California','None','None','["None"]','mt-baldy',1,0);
INSERT INTO resort VALUES(339,'Snow Summit','CA',NULL,'US','US','United States',NULL,'CA','California','None','None','["None"]','snow-summit',1,0);
INSERT INTO resort VALUES(340,'Snow Valley','CA',NULL,'US','US','United States',NULL,'CA','California','None','None','["None"]','snow-valley',1,0);
INSERT INTO resort VALUES(341,'Dodge Ridge','CA',NULL,'US','US','United States',NULL,'CA','California','None','None','["None"]','dodge-ridge',1,0);
INSERT INTO resort VALUES(342,'Berkshire East','MA',NULL,'US','US','United States',NULL,'MA','Massachusetts','Indy','Indy','["Indy"]','berkshire-east',1,0);
INSERT INTO resort VALUES(343,'Mt. Crescent','IA',NULL,'US','US','United States',NULL,'IA','Iowa','None','None','["None"]','mt-crescent',1,0);
INSERT INTO resort VALUES(344,'Echo Mountain','CO',NULL,'US','US','United States',NULL,'CO','Colorado','None','None','["None"]','echo-mountain',1,0);
INSERT INTO resort VALUES(345,'Hoedown Hill','CO',NULL,'US','US','United States',NULL,'CO','Colorado','None','None','["None"]','hoedown-hill',1,0);
INSERT INTO resort VALUES(346,'Howelsen Hill','CO',NULL,'US','US','United States',NULL,'CO','Colorado','None','None','["None"]','howelsen-hill',1,0);
INSERT INTO resort VALUES(347,'Mt. Brighton','MI',NULL,'US','US','United States',NULL,'MI','Michigan','Epic','Epic','["Epic"]','mt-brighton',1,0);
INSERT INTO resort VALUES(348,'The Highlands','MI',NULL,'US','US','United States',NULL,'MI','Michigan','Ikon','Ikon','["Ikon"]','the-highlands',1,0);
INSERT INTO resort VALUES(349,'Afton Alps','MN',NULL,'US','US','United States',NULL,'MN','Minnesota','Epic','Epic','["Epic"]','afton-alps',1,0);
INSERT INTO resort VALUES(350,'Lutsen Mountains','MN',NULL,'US','US','United States',NULL,'MN','Minnesota','Ikon','Ikon','["Ikon"]','lutsen-mountains',1,0);
INSERT INTO resort VALUES(351,'Big Sky Resort','MT',NULL,'US','US','United States',NULL,'MT','Montana','Ikon','Ikon','["Ikon"]','big-sky-resort',1,0);
INSERT INTO resort VALUES(352,'Attitash','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','Epic','Epic','["Epic"]','attitash',1,0);
INSERT INTO resort VALUES(353,'Mountain Creek','NJ',NULL,'US','US','United States',NULL,'NJ','New Jersey','Ikon','Ikon','["Ikon"]','mountain-creek',1,0);
INSERT INTO resort VALUES(354,'Sipapu','NM',NULL,'US','US','United States',NULL,'NM','New Mexico','Indy','Indy','["Indy"]','sipapu',1,0);
INSERT INTO resort VALUES(355,'Plattekill','NY',NULL,'US','US','United States',NULL,'NY','New York','Indy','Indy','["Indy"]','plattekill',1,0);
INSERT INTO resort VALUES(356,'Big Boulder','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','Epic','Epic','["Epic"]','big-boulder',1,0);
INSERT INTO resort VALUES(357,'Hidden Valley','NJ',NULL,'US','US','United States',NULL,'NJ','New Jersey','None','None','["None"]','hidden-valley',1,0);
INSERT INTO resort VALUES(358,'Jack Frost','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','Epic','Epic','["Epic"]','jack-frost',1,0);
INSERT INTO resort VALUES(359,'Laurel Mountain','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','Epic','Epic','["Epic"]','laurel-mountain',1,0);
INSERT INTO resort VALUES(360,'Taos','NM',NULL,'US','US','United States',NULL,'NM','New Mexico','Ikon','Ikon,Mountain Collective','["Ikon", "Mountain Collective"]','taos',1,0);
INSERT INTO resort VALUES(361,'Caberfae Peaks','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','caberfae-peaks',1,0);
INSERT INTO resort VALUES(362,'Buck Hill','MN',NULL,'US','US','United States',NULL,'MN','Minnesota','None','None','["None"]','buck-hill',1,0);
INSERT INTO resort VALUES(363,'Wild Mountain','MN',NULL,'US','US','United States',NULL,'MN','Minnesota','None','None','["None"]','wild-mountain',1,0);
INSERT INTO resort VALUES(364,'Giants Ridge','MN',NULL,'US','US','United States',NULL,'MN','Minnesota','None','None','["None"]','giants-ridge',1,0);
INSERT INTO resort VALUES(365,'Blacktail Mountain','MT',NULL,'US','US','United States',NULL,'MT','Montana','None','None','["None"]','blacktail-mountain',1,0);
INSERT INTO resort VALUES(366,'Great Divide','MT',NULL,'US','US','United States',NULL,'MT','Montana','None','None','["None"]','great-divide',1,0);
INSERT INTO resort VALUES(367,'Maverick Mountain','MT',NULL,'US','US','United States',NULL,'MT','Montana','None','None','["None"]','maverick-mountain',1,0);
INSERT INTO resort VALUES(368,'Showdown','MT',NULL,'US','US','United States',NULL,'MT','Montana','None','None','["None"]','showdown',1,0);
INSERT INTO resort VALUES(369,'Mount Kato','MN',NULL,'US','US','United States',NULL,'MN','Minnesota','None','None','["None"]','mount-kato',1,0);
INSERT INTO resort VALUES(370,'Spirit Mountain','MN',NULL,'US','US','United States',NULL,'MN','Minnesota','None','None','["None"]','spirit-mountain',1,0);
INSERT INTO resort VALUES(371,'Cataloochee','NC',NULL,'US','US','United States',NULL,'NC','North Carolina','None','None','["None"]','cataloochee',1,0);
INSERT INTO resort VALUES(372,'Gunstock','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','gunstock',1,0);
INSERT INTO resort VALUES(373,'Wintergreen','VA',NULL,'US','US','United States',NULL,'VA','Virginia','Epic','Epic','["Epic"]','wintergreen',1,0);
INSERT INTO resort VALUES(374,'Killington-Pico','VT',NULL,'US','US','United States',NULL,'VT','Vermont','Ikon','Ikon','["Ikon"]','killington-pico',1,0);
INSERT INTO resort VALUES(375,'Magic Mountain','ID',NULL,'US','US','United States',NULL,'ID','Idaho','None','None','["None"]','magic-mountain',1,0);
INSERT INTO resort VALUES(376,'Wilmot Mountain','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','Epic','Epic','["Epic"]','wilmot-mountain',1,0);
INSERT INTO resort VALUES(377,'Alyeska','AK',NULL,'US','US','United States',NULL,'AK','Alaska','Ikon','Ikon','["Ikon"]','alyeska',1,0);
INSERT INTO resort VALUES(378,'Big Bear Mountain','CA',NULL,'US','US','United States',NULL,'CA','California','Ikon','Ikon','["Ikon"]','big-bear-mountain',1,0);
INSERT INTO resort VALUES(379,'Alpine Valley','OH',NULL,'US','US','United States',NULL,'OH','Ohio','Epic','Epic','["Epic"]','alpine-valley',1,0);
INSERT INTO resort VALUES(380,'Bryce Resort','VA',NULL,'US','US','United States',NULL,'VA','Virginia','None','None','["None"]','bryce-resort',1,0);
INSERT INTO resort VALUES(381,'The Homestead','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','the-homestead',1,0);
INSERT INTO resort VALUES(382,'Burke Mountain','VT',NULL,'US','US','United States',NULL,'VT','Vermont','None','None','["None"]','burke-mountain',1,0);
INSERT INTO resort VALUES(383,'Suicide Six','VT',NULL,'US','US','United States',NULL,'VT','Vermont','None','None','["None"]','suicide-six',1,0);
INSERT INTO resort VALUES(384,'Mt. Bohemia','MI',NULL,'US','US','United States',NULL,'MI','Michigan','Indy','Indy','["Indy"]','mt-bohemia',1,0);
INSERT INTO resort VALUES(385,'Camelback','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','Ikon','Ikon','["Ikon"]','camelback',1,0);
INSERT INTO resort VALUES(386,'Whitefish','MT',NULL,'US','US','United States',NULL,'MT','Montana','None','None','["None"]','whitefish',1,0);
INSERT INTO resort VALUES(387,'Pleasant Mountain','ME',NULL,'US','US','United States',NULL,'ME','Maine','None','None','["None"]','pleasant-mountain',1,0);
INSERT INTO resort VALUES(388,'Hatley Pointe','NC',NULL,'US','US','United States',NULL,'NC','North Carolina','None','None','["None"]','hatley-pointe',1,0);
INSERT INTO resort VALUES(389,'Aspen Mountain','CO',NULL,'US','US','United States',NULL,'CO','Colorado','Ikon','Ikon','["Ikon"]','aspen-mountain',1,0);
INSERT INTO resort VALUES(390,'Red Lodge','MT',NULL,'US','US','United States',NULL,'MT','Montana','None','None','["None"]','red-lodge',1,0);
INSERT INTO resort VALUES(391,'Crystal Ridge','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','crystal-ridge',1,0);
INSERT INTO resort VALUES(392,'Wildcat','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','Epic','Epic','["Epic"]','wildcat',1,0);
INSERT INTO resort VALUES(393,'Powder Ridge','MN',NULL,'US','US','United States',NULL,'MN','Minnesota','None','None','["None"]','powder-ridge',1,0);
INSERT INTO resort VALUES(394,'Baker Mountain','ME',NULL,'US','US','United States',NULL,'ME','Maine','None','None','["None"]','baker-mountain',1,0);
INSERT INTO resort VALUES(395,'Big Squaw','ME',NULL,'US','US','United States',NULL,'ME','Maine','None','None','["None"]','big-squaw',1,0);
INSERT INTO resort VALUES(396,'Eaton Mountain','ME',NULL,'US','US','United States',NULL,'ME','Maine','None','None','["None"]','eaton-mountain',1,0);
INSERT INTO resort VALUES(397,'Hermon Mountain','ME',NULL,'US','US','United States',NULL,'ME','Maine','None','None','["None"]','hermon-mountain',1,0);
INSERT INTO resort VALUES(398,'Lonesome Pine Trails','ME',NULL,'US','US','United States',NULL,'ME','Maine','None','None','["None"]','lonesome-pine-trails',1,0);
INSERT INTO resort VALUES(399,'Pinnacle Ski Club','ME',NULL,'US','US','United States',NULL,'ME','Maine','None','None','["None"]','pinnacle-ski-club',1,0);
INSERT INTO resort VALUES(400,'Powderhouse Hill','ME',NULL,'US','US','United States',NULL,'ME','Maine','None','None','["None"]','powderhouse-hill',1,0);
INSERT INTO resort VALUES(401,'Quoggy Jo','ME',NULL,'US','US','United States',NULL,'ME','Maine','None','None','["None"]','quoggy-jo',1,0);
INSERT INTO resort VALUES(402,'Titcomb Mountain','ME',NULL,'US','US','United States',NULL,'ME','Maine','None','None','["None"]','titcomb-mountain',1,0);
INSERT INTO resort VALUES(403,'Otis Ridge','MA',NULL,'US','US','United States',NULL,'MA','Massachusetts','None','None','["None"]','otis-ridge',1,0);
INSERT INTO resort VALUES(404,'Ski Bradford','MA',NULL,'US','US','United States',NULL,'MA','Massachusetts','None','None','["None"]','ski-bradford',1,0);
INSERT INTO resort VALUES(405,'Ski Ward','MA',NULL,'US','US','United States',NULL,'MA','Massachusetts','None','None','["None"]','ski-ward',1,0);
INSERT INTO resort VALUES(406,'Arrowhead','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','arrowhead',1,0);
INSERT INTO resort VALUES(407,'Campton Mountain','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','campton-mountain',1,0);
INSERT INTO resort VALUES(408,'Crotched Mountain','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','crotched-mountain',1,0);
INSERT INTO resort VALUES(409,'Dartmouth Skiway','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','dartmouth-skiway',1,0);
INSERT INTO resort VALUES(410,'Granite Gorge','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','granite-gorge',1,0);
INSERT INTO resort VALUES(411,'Mount Prospect','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','mount-prospect',1,0);
INSERT INTO resort VALUES(412,'Storrs Hill','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','storrs-hill',1,0);
INSERT INTO resort VALUES(413,'Whaleback','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','whaleback',1,0);
INSERT INTO resort VALUES(414,'Yawgoo Valley','RI',NULL,'US','US','United States',NULL,'RI','Rhode Island','None','None','["None"]','yawgoo-valley',1,0);
INSERT INTO resort VALUES(415,'Bellows Falls Ski Tow','VT',NULL,'US','US','United States',NULL,'VT','Vermont','None','None','["None"]','bellows-falls-ski-tow',1,0);
INSERT INTO resort VALUES(416,'Cochran''s Ski Area','VT',NULL,'US','US','United States',NULL,'VT','Vermont','None','None','["None"]','cochran-s-ski-area',1,0);
INSERT INTO resort VALUES(417,'Harrington Hill','VT',NULL,'US','US','United States',NULL,'VT','Vermont','None','None','["None"]','harrington-hill',1,0);
INSERT INTO resort VALUES(418,'Hard ''Ack','VT',NULL,'US','US','United States',NULL,'VT','Vermont','None','None','["None"]','hard-ack',1,0);
INSERT INTO resort VALUES(419,'Haystack','VT',NULL,'US','US','United States',NULL,'VT','Vermont','None','None','["None"]','haystack',1,0);
INSERT INTO resort VALUES(420,'Living Memorial Park','VT',NULL,'US','US','United States',NULL,'VT','Vermont','None','None','["None"]','living-memorial-park',1,0);
INSERT INTO resort VALUES(421,'Lyndon Outing Club','VT',NULL,'US','US','United States',NULL,'VT','Vermont','None','None','["None"]','lyndon-outing-club',1,0);
INSERT INTO resort VALUES(422,'Middlebury College Snow Bowl','VT',NULL,'US','US','United States',NULL,'VT','Vermont','None','None','["None"]','middlebury-college-snow-bowl',1,0);
INSERT INTO resort VALUES(423,'Plymouth Notch','VT',NULL,'US','US','United States',NULL,'VT','Vermont','None','None','["None"]','plymouth-notch',1,0);
INSERT INTO resort VALUES(424,'Big Snow American Dream','NJ',NULL,'US','US','United States',NULL,'NJ','New Jersey','None','None','["None"]','big-snow-american-dream',1,0);
INSERT INTO resort VALUES(425,'Campgaw Mountain','NJ',NULL,'US','US','United States',NULL,'NJ','New Jersey','None','None','["None"]','campgaw-mountain',1,0);
INSERT INTO resort VALUES(426,'Buffalo Ski Club','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','buffalo-ski-club',1,0);
INSERT INTO resort VALUES(427,'Bousquet','MA',NULL,'US','US','United States',NULL,'MA','Massachusetts','None','None','["None"]','bousquet',1,0);
INSERT INTO resort VALUES(428,'Easton','MA',NULL,'US','US','United States',NULL,'MA','Massachusetts','None','None','["None"]','easton',1,0);
INSERT INTO resort VALUES(429,'Mount Greylock','MA',NULL,'US','US','United States',NULL,'MA','Massachusetts','None','None','["None"]','mount-greylock',1,0);
INSERT INTO resort VALUES(430,'Nashoba Valley','MA',NULL,'US','US','United States',NULL,'MA','Massachusetts','None','None','["None"]','nashoba-valley',1,0);
INSERT INTO resort VALUES(431,'Mount Sunapee','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','Epic','Epic','["Epic"]','mount-sunapee',1,0);
INSERT INTO resort VALUES(432,'Abenaki','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','abenaki',1,0);
INSERT INTO resort VALUES(433,'Mount Jefferson','ME',NULL,'US','US','United States',NULL,'ME','Maine','None','None','["None"]','mount-jefferson',1,0);
INSERT INTO resort VALUES(434,'Mt. Abram','ME',NULL,'US','US','United States',NULL,'ME','Maine','None','None','["None"]','mt-abram',1,0);
INSERT INTO resort VALUES(435,'Whitefish Mountain Resort','MT',NULL,'US','US','United States',NULL,'MT','Montana','None','None','["None"]','whitefish-mountain-resort',1,0);
INSERT INTO resort VALUES(436,'Kanc','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','kanc',1,0);
INSERT INTO resort VALUES(437,'McIntyre','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','mcintyre',1,0);
INSERT INTO resort VALUES(438,'Mount Eustis','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','mount-eustis',1,0);
INSERT INTO resort VALUES(439,'Tenney Mountain','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','tenney-mountain',1,0);
INSERT INTO resort VALUES(440,'The Balsams','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','the-balsams',1,0);
INSERT INTO resort VALUES(441,'Windham','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','windham',1,0);
INSERT INTO resort VALUES(442,'Beartown','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','beartown',1,0);
INSERT INTO resort VALUES(443,'Big Tupper','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','big-tupper',1,0);
INSERT INTO resort VALUES(444,'Brantling','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','brantling',1,0);
INSERT INTO resort VALUES(445,'Catamount','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','catamount',1,0);
INSERT INTO resort VALUES(446,'Dry Hill','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','dry-hill',1,0);
INSERT INTO resort VALUES(447,'Hickory','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','hickory',1,0);
INSERT INTO resort VALUES(448,'Quechee Lakes','VT',NULL,'US','US','United States',NULL,'VT','Vermont','None','None','["None"]','quechee-lakes',1,0);
INSERT INTO resort VALUES(449,'Kissing Bridge','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','kissing-bridge',1,0);
INSERT INTO resort VALUES(450,'Labrador Mountain','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','labrador-mountain',1,0);
INSERT INTO resort VALUES(451,'McCauley Mountain','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','mccauley-mountain',1,0);
INSERT INTO resort VALUES(452,'Royal Mountain','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','royal-mountain',1,0);
INSERT INTO resort VALUES(453,'Swain','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','swain',1,0);
INSERT INTO resort VALUES(454,'Sugar Hill','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','sugar-hill',1,0);
INSERT INTO resort VALUES(455,'Titus Mountain','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','titus-mountain',1,0);
INSERT INTO resort VALUES(456,'Toggenburg Mountain','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','toggenburg-mountain',1,0);
INSERT INTO resort VALUES(457,'West Mountain','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','west-mountain',1,0);
INSERT INTO resort VALUES(458,'Willard Mountain','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','willard-mountain',1,0);
INSERT INTO resort VALUES(459,'Boyce Park','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','None','None','["None"]','boyce-park',1,0);
INSERT INTO resort VALUES(460,'Ski Big Bear','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','None','None','["None"]','ski-big-bear',1,0);
INSERT INTO resort VALUES(461,'Cloudmont Ski & Golf Resort','AL',NULL,'US','US','United States',NULL,'AL','Alabama','None','None','["None"]','cloudmont-ski-golf-resort',1,0);
INSERT INTO resort VALUES(462,'Wolf Ridge','NC',NULL,'US','US','United States',NULL,'NC','North Carolina','None','None','["None"]','wolf-ridge',1,0);
INSERT INTO resort VALUES(463,'Oglebay Resort','WV',NULL,'US','US','United States',NULL,'WV','West Virginia','None','None','["None"]','oglebay-resort',1,0);
INSERT INTO resort VALUES(464,'Ski Four Lakes','IL',NULL,'US','US','United States',NULL,'IL','Illinois','None','None','["None"]','ski-four-lakes',1,0);
INSERT INTO resort VALUES(465,'Ski Snowstar','IL',NULL,'US','US','United States',NULL,'IL','Illinois','None','None','["None"]','ski-snowstar',1,0);
INSERT INTO resort VALUES(466,'Villa Olivia','IL',NULL,'US','US','United States',NULL,'IL','Illinois','None','None','["None"]','villa-olivia',1,0);
INSERT INTO resort VALUES(467,'Challenge Mountain','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','challenge-mountain',1,0);
INSERT INTO resort VALUES(468,'Garland Resort','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','garland-resort',1,0);
INSERT INTO resort VALUES(469,'Marquette Mountain','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','marquette-mountain',1,0);
INSERT INTO resort VALUES(470,'Mt. Holiday','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','mt-holiday',1,0);
INSERT INTO resort VALUES(471,'Petoskey Winter Sports Park','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','petoskey-winter-sports-park',1,0);
INSERT INTO resort VALUES(472,'Pine Mountain Resort','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','pine-mountain-resort',1,0);
INSERT INTO resort VALUES(473,'Porcupine Mountains','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','porcupine-mountains',1,0);
INSERT INTO resort VALUES(474,'Ski Brule','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','ski-brule',1,0);
INSERT INTO resort VALUES(475,'Snow Snake Ski & Golf','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','snow-snake-ski-golf',1,0);
INSERT INTO resort VALUES(476,'Treetops Resort','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','treetops-resort',1,0);
INSERT INTO resort VALUES(477,'Sleepy Hollow','IA',NULL,'US','US','United States',NULL,'IA','Iowa','None','None','["None"]','sleepy-hollow',1,0);
INSERT INTO resort VALUES(478,'Chestnut Mountain','IL',NULL,'US','US','United States',NULL,'IL','Illinois','None','None','["None"]','chestnut-mountain',1,0);
INSERT INTO resort VALUES(479,'Raging Buffalo','IL',NULL,'US','US','United States',NULL,'IL','Illinois','None','None','["None"]','raging-buffalo',1,0);
INSERT INTO resort VALUES(480,'Apple Mountain','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','apple-mountain',1,0);
INSERT INTO resort VALUES(481,'Mt. Holly','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','mt-holly',1,0);
INSERT INTO resort VALUES(482,'Big Powderhorn','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','big-powderhorn',1,0);
INSERT INTO resort VALUES(483,'Bittersweet','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','bittersweet',1,0);
INSERT INTO resort VALUES(484,'Blackjack','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','blackjack',1,0);
INSERT INTO resort VALUES(485,'Cannonsburg','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','cannonsburg',1,0);
INSERT INTO resort VALUES(486,'Hickory Hills','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','hickory-hills',1,0);
INSERT INTO resort VALUES(487,'Indianhead','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','indianhead',1,0);
INSERT INTO resort VALUES(488,'Mont Ripley','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','mont-ripley',1,0);
INSERT INTO resort VALUES(489,'Liberty Mountain','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','Epic','Epic','["Epic"]','liberty-mountain',1,0);
INSERT INTO resort VALUES(490,'Al Quaal','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','al-quaal',1,0);
INSERT INTO resort VALUES(491,'Mt. McSauba','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','mt-mcsauba',1,0);
INSERT INTO resort VALUES(492,'Mt. Zion','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','mt-zion',1,0);
INSERT INTO resort VALUES(493,'Mulligan''s Hollow','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','mulligan-s-hollow',1,0);
INSERT INTO resort VALUES(494,'Norway Mountain','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','norway-mountain',1,0);
INSERT INTO resort VALUES(495,'Pine Knob','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','pine-knob',1,0);
INSERT INTO resort VALUES(496,'Swiss Valley','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','swiss-valley',1,0);
INSERT INTO resort VALUES(497,'Timber Ridge','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','timber-ridge',1,0);
INSERT INTO resort VALUES(498,'Otsego','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','otsego',1,0);
INSERT INTO resort VALUES(499,'Sapphire','NC',NULL,'US','US','United States',NULL,'NC','North Carolina','None','None','["None"]','sapphire',1,0);
INSERT INTO resort VALUES(500,'Mount Peter','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','mount-peter',1,0);
INSERT INTO resort VALUES(501,'Snow Ridge','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','snow-ridge',1,0);
INSERT INTO resort VALUES(502,'Song Mountain','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','song-mountain',1,0);
INSERT INTO resort VALUES(503,'Thunder Ridge','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','thunder-ridge',1,0);
INSERT INTO resort VALUES(504,'Woods Valley','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','woods-valley',1,0);
INSERT INTO resort VALUES(505,'Bear Creek','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','None','None','["None"]','bear-creek',1,0);
INSERT INTO resort VALUES(506,'Denton','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','None','None','["None"]','denton',1,0);
INSERT INTO resort VALUES(507,'Montage Mountain','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','None','None','["None"]','montage-mountain',1,0);
INSERT INTO resort VALUES(508,'Spring Mountain','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','None','None','["None"]','spring-mountain',1,0);
INSERT INTO resort VALUES(509,'Tussey Mountain','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','None','None','["None"]','tussey-mountain',1,0);
INSERT INTO resort VALUES(510,'Paoli Peaks','IN',NULL,'US','US','United States',NULL,'IN','Indiana','Epic','Epic','["Epic"]','paoli-peaks',1,0);
INSERT INTO resort VALUES(511,'Blue Knob','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','None','None','["None"]','blue-knob',1,0);
INSERT INTO resort VALUES(512,'Eagle Rock','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','None','None','["None"]','eagle-rock',1,0);
INSERT INTO resort VALUES(513,'Mountain View','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','None','None','["None"]','mountain-view',1,0);
INSERT INTO resort VALUES(514,'Roundtop','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','Epic','Epic','["Epic"]','roundtop',1,0);
INSERT INTO resort VALUES(515,'Sawmill','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','None','None','["None"]','sawmill',1,0);
INSERT INTO resort VALUES(516,'Whitetail','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','Epic','Epic','["Epic"]','whitetail',1,0);
INSERT INTO resort VALUES(517,'Perfect North Slopes','IN',NULL,'US','US','United States',NULL,'IN','Indiana','Epic','Epic','["Epic"]','perfect-north-slopes',1,0);
INSERT INTO resort VALUES(518,'Andes Tower Hills','MN',NULL,'US','US','United States',NULL,'MN','Minnesota','None','None','["None"]','andes-tower-hills',1,0);
INSERT INTO resort VALUES(519,'Detroit Mountain','MN',NULL,'US','US','United States',NULL,'MN','Minnesota','None','None','["None"]','detroit-mountain',1,0);
INSERT INTO resort VALUES(520,'Mount Itasca','MN',NULL,'US','US','United States',NULL,'MN','Minnesota','None','None','["None"]','mount-itasca',1,0);
INSERT INTO resort VALUES(521,'Ski Gull','MN',NULL,'US','US','United States',NULL,'MN','Minnesota','None','None','["None"]','ski-gull',1,0);
INSERT INTO resort VALUES(522,'Snow Creek','KS',NULL,'US','US','United States',NULL,'KS','Kansas','None','None','["None"]','snow-creek',1,0);
INSERT INTO resort VALUES(523,'Frost Fire','ND',NULL,'US','US','United States',NULL,'ND','North Dakota','None','None','["None"]','frost-fire',1,0);
INSERT INTO resort VALUES(524,'Deer Mountain','SD',NULL,'US','US','United States',NULL,'SD','South Dakota','None','None','["None"]','deer-mountain',1,0);
INSERT INTO resort VALUES(525,'Great Bear','SD',NULL,'US','US','United States',NULL,'SD','South Dakota','None','None','["None"]','great-bear',1,0);
INSERT INTO resort VALUES(526,'Book Across the Bay','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','book-across-the-bay',1,0);
INSERT INTO resort VALUES(527,'Camp 10','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','camp-10',1,0);
INSERT INTO resort VALUES(528,'Christie Mountain','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','christie-mountain',1,0);
INSERT INTO resort VALUES(529,'Fox Hill Ski Area','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','fox-hill-ski-area',1,0);
INSERT INTO resort VALUES(530,'Kettlebowl','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','kettlebowl',1,0);
INSERT INTO resort VALUES(531,'Keyes Peak','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','keyes-peak',1,0);
INSERT INTO resort VALUES(532,'Mont Du Lac','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','mont-du-lac',1,0);
INSERT INTO resort VALUES(533,'Navarino Slopes','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','navarino-slopes',1,0);
INSERT INTO resort VALUES(534,'Nordic Mountain','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','nordic-mountain',1,0);
INSERT INTO resort VALUES(535,'Nutt Hill','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','nutt-hill',1,0);
INSERT INTO resort VALUES(536,'Powers Bluff','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','powers-bluff',1,0);
INSERT INTO resort VALUES(537,'Standing Rocks','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','standing-rocks',1,0);
INSERT INTO resort VALUES(538,'Telemark Lodge','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','telemark-lodge',1,0);
INSERT INTO resort VALUES(539,'Trollhaugen','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','trollhaugen',1,0);
INSERT INTO resort VALUES(540,'Tyrol Basin','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','tyrol-basin',1,0);
INSERT INTO resort VALUES(541,'Whitetail Ridge','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','whitetail-ridge',1,0);
INSERT INTO resort VALUES(542,'Elk Ridge Ski Area','AZ',NULL,'US','US','United States',NULL,'AZ','Arizona','None','None','["None"]','elk-ridge-ski-area',1,0);
INSERT INTO resort VALUES(543,'Chapman Hill Ski Area','CO',NULL,'US','US','United States',NULL,'CO','Colorado','None','None','["None"]','chapman-hill-ski-area',1,0);
INSERT INTO resort VALUES(544,'Cranor Ski Area','CO',NULL,'US','US','United States',NULL,'CO','Colorado','None','None','["None"]','cranor-ski-area',1,0);
INSERT INTO resort VALUES(545,'Hesperus Ski Area','CO',NULL,'US','US','United States',NULL,'CO','Colorado','None','None','["None"]','hesperus-ski-area',1,0);
INSERT INTO resort VALUES(546,'Kendall Mountain Ski Area','CO',NULL,'US','US','United States',NULL,'CO','Colorado','None','None','["None"]','kendall-mountain-ski-area',1,0);
INSERT INTO resort VALUES(547,'Lake City Ski Hill','CO',NULL,'US','US','United States',NULL,'CO','Colorado','None','None','["None"]','lake-city-ski-hill',1,0);
INSERT INTO resort VALUES(548,'Ski Granby Ranch','CO',NULL,'US','US','United States',NULL,'CO','Colorado','None','None','["None"]','ski-granby-ranch',1,0);
INSERT INTO resort VALUES(549,'Bald Mountain','ID',NULL,'US','US','United States',NULL,'ID','Idaho','None','None','["None"]','bald-mountain',1,0);
INSERT INTO resort VALUES(550,'Cottonwood Butte','ID',NULL,'US','US','United States',NULL,'ID','Idaho','None','None','["None"]','cottonwood-butte',1,0);
INSERT INTO resort VALUES(551,'Little Ski Hill','ID',NULL,'US','US','United States',NULL,'ID','Idaho','None','None','["None"]','little-ski-hill',1,0);
INSERT INTO resort VALUES(552,'Lost Trail Powder Mountain','ID',NULL,'US','US','United States',NULL,'ID','Idaho','None','None','["None"]','lost-trail-powder-mountain',1,0);
INSERT INTO resort VALUES(553,'Pomerelle','ID',NULL,'US','US','United States',NULL,'ID','Idaho','None','None','["None"]','pomerelle',1,0);
INSERT INTO resort VALUES(554,'Rotarun','ID',NULL,'US','US','United States',NULL,'ID','Idaho','None','None','["None"]','rotarun',1,0);
INSERT INTO resort VALUES(555,'Snowhaven','ID',NULL,'US','US','United States',NULL,'ID','Idaho','None','None','["None"]','snowhaven',1,0);
INSERT INTO resort VALUES(556,'Sandia Peak','NM',NULL,'US','US','United States',NULL,'NM','New Mexico','None','None','["None"]','sandia-peak',1,0);
INSERT INTO resort VALUES(557,'Ski Cloudcroft','NM',NULL,'US','US','United States',NULL,'NM','New Mexico','None','None','["None"]','ski-cloudcroft',1,0);
INSERT INTO resort VALUES(558,'Big Horn','WY',NULL,'US','US','United States',NULL,'WY','Wyoming','None','None','["None"]','big-horn',1,0);
INSERT INTO resort VALUES(559,'Pine Creek','WY',NULL,'US','US','United States',NULL,'WY','Wyoming','None','None','["None"]','pine-creek',1,0);
INSERT INTO resort VALUES(560,'Arctic Valley','AK',NULL,'US','US','United States',NULL,'AK','Alaska','None','None','["None"]','arctic-valley',1,0);
INSERT INTO resort VALUES(561,'Hilltop','AK',NULL,'US','US','United States',NULL,'AK','Alaska','None','None','["None"]','hilltop',1,0);
INSERT INTO resort VALUES(562,'Mad River','OH',NULL,'US','US','United States',NULL,'OH','Ohio','Epic','Epic','["Epic"]','mad-river',1,0);
INSERT INTO resort VALUES(563,'Snow Trails','OH',NULL,'US','US','United States',NULL,'OH','Ohio','Epic','Epic','["Epic"]','snow-trails',1,0);
INSERT INTO resort VALUES(564,'Buena Vista','MN',NULL,'US','US','United States',NULL,'MN','Minnesota','None','None','["None"]','buena-vista',1,0);
INSERT INTO resort VALUES(565,'Coffee Mill','MN',NULL,'US','US','United States',NULL,'MN','Minnesota','None','None','["None"]','coffee-mill',1,0);
INSERT INTO resort VALUES(566,'Hyland','MN',NULL,'US','US','United States',NULL,'MN','Minnesota','None','None','["None"]','hyland',1,0);
INSERT INTO resort VALUES(567,'Chester Bowl','MN',NULL,'US','US','United States',NULL,'MN','Minnesota','None','None','["None"]','chester-bowl',1,0);
INSERT INTO resort VALUES(568,'Bottineau','ND',NULL,'US','US','United States',NULL,'ND','North Dakota','None','None','["None"]','bottineau',1,0);
INSERT INTO resort VALUES(569,'Montana Snowbowl','MT',NULL,'US','US','United States',NULL,'MT','Montana','None','None','["None"]','montana-snowbowl',1,0);
INSERT INTO resort VALUES(570,'Moonlight Basin','MT',NULL,'US','US','United States',NULL,'MT','Montana','None','None','["None"]','moonlight-basin',1,0);
INSERT INTO resort VALUES(571,'Turner Mountain','MT',NULL,'US','US','United States',NULL,'MT','Montana','None','None','["None"]','turner-mountain',1,0);
INSERT INTO resort VALUES(572,'Yellowstone Club','MT',NULL,'US','US','United States',NULL,'MT','Montana','None','None','["None"]','yellowstone-club',1,0);
INSERT INTO resort VALUES(573,'Teton Pass','WY',NULL,'US','US','United States',NULL,'WY','Wyoming','None','None','["None"]','teton-pass',1,0);
INSERT INTO resort VALUES(574,'Bear Paw','MT',NULL,'US','US','United States',NULL,'MT','Montana','None','None','["None"]','bear-paw',1,0);
INSERT INTO resort VALUES(575,'Boston Mills','OH',NULL,'US','US','United States',NULL,'OH','Ohio','Epic','Epic','["Epic"]','boston-mills',1,0);
INSERT INTO resort VALUES(576,'Big Creek','OH',NULL,'US','US','United States',NULL,'OH','Ohio','None','None','["None"]','big-creek',1,0);
INSERT INTO resort VALUES(577,'Mt Aggie','TX',NULL,'US','US','United States',NULL,'TX','Texas','None','None','["None"]','mt-aggie',1,0);
INSERT INTO resort VALUES(578,'Bruce Mound','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','bruce-mound',1,0);
INSERT INTO resort VALUES(579,'Christmas Mountain','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','christmas-mountain',1,0);
INSERT INTO resort VALUES(580,'Little Switzerland','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','little-switzerland',1,0);
INSERT INTO resort VALUES(581,'Badlands','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','badlands',1,0);
INSERT INTO resort VALUES(582,'Heiliger Huegel','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','heiliger-huegel',1,0);
INSERT INTO resort VALUES(583,'Blackhawk','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','blackhawk',1,0);
INSERT INTO resort VALUES(584,'Ausblick','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','ausblick',1,0);
INSERT INTO resort VALUES(585,'Kewaunee County','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','kewaunee-county',1,0);
INSERT INTO resort VALUES(586,'Sunburst','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','sunburst',1,0);
INSERT INTO resort VALUES(587,'Triangle','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','triangle',1,0);
INSERT INTO resort VALUES(588,'The Mountain Top','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','the-mountain-top',1,0);
INSERT INTO resort VALUES(589,'Ashwabay','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','ashwabay',1,0);
INSERT INTO resort VALUES(590,'Mt. La Crosse','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','mt-la-crosse',1,0);
INSERT INTO resort VALUES(591,'Sleeping Giant','WY',NULL,'US','US','United States',NULL,'WY','Wyoming','None','None','["None"]','sleeping-giant',1,0);
INSERT INTO resort VALUES(592,'Majestic Heli Ski','AK',NULL,'US','US','United States',NULL,'AK','Alaska','None','None','["None"]','majestic-heli-ski',1,0);
INSERT INTO resort VALUES(593,'Moose Mountain','AK',NULL,'US','US','United States',NULL,'AK','Alaska','None','None','["None"]','moose-mountain',1,0);
INSERT INTO resort VALUES(594,'Mount Eyak','AK',NULL,'US','US','United States',NULL,'AK','Alaska','None','None','["None"]','mount-eyak',1,0);
INSERT INTO resort VALUES(595,'Skiland','AK',NULL,'US','US','United States',NULL,'AK','Alaska','None','None','["None"]','skiland',1,0);
INSERT INTO resort VALUES(596,'Alpine Meadows','CA',NULL,'US','US','United States',NULL,'CA','California','None','None','["None"]','alpine-meadows',1,0);
INSERT INTO resort VALUES(597,'Alta Sierra','CA',NULL,'US','US','United States',NULL,'CA','California','None','None','["None"]','alta-sierra',1,0);
INSERT INTO resort VALUES(598,'Badger Pass','CA',NULL,'US','US','United States',NULL,'CA','California','None','None','["None"]','badger-pass',1,0);
INSERT INTO resort VALUES(599,'Buckhorn Ski Club','CA',NULL,'US','US','United States',NULL,'CA','California','None','None','["None"]','buckhorn-ski-club',1,0);
INSERT INTO resort VALUES(600,'Donner Ski Ranch','CA',NULL,'US','US','United States',NULL,'CA','California','None','None','["None"]','donner-ski-ranch',1,0);
INSERT INTO resort VALUES(601,'Granlibakken','CA',NULL,'US','US','United States',NULL,'CA','California','None','None','["None"]','granlibakken',1,0);
INSERT INTO resort VALUES(602,'Mount Shasta Ski Park','CA',NULL,'US','US','United States',NULL,'CA','California','None','None','["None"]','mount-shasta-ski-park',1,0);
INSERT INTO resort VALUES(603,'Mount Waterman','CA',NULL,'US','US','United States',NULL,'CA','California','None','None','["None"]','mount-waterman',1,0);
INSERT INTO resort VALUES(604,'Mountain High','CA',NULL,'US','US','United States',NULL,'CA','California','None','None','["None"]','mountain-high',1,0);
INSERT INTO resort VALUES(605,'Soda Springs','CA',NULL,'US','US','United States',NULL,'CA','California','None','None','["None"]','soda-springs',1,0);
INSERT INTO resort VALUES(606,'Tahoe Donner Downhill','CA',NULL,'US','US','United States',NULL,'CA','California','None','None','["None"]','tahoe-donner-downhill',1,0);
INSERT INTO resort VALUES(607,'Mount Rose','NV',NULL,'US','US','United States',NULL,'NV','Nevada','None','None','["None"]','mount-rose',1,0);
INSERT INTO resort VALUES(608,'Cooper Spur','OR',NULL,'US','US','United States',NULL,'OR','Oregon','None','None','["None"]','cooper-spur',1,0);
INSERT INTO resort VALUES(609,'Ferguson Ridge','OR',NULL,'US','US','United States',NULL,'OR','Oregon','None','None','["None"]','ferguson-ridge',1,0);
INSERT INTO resort VALUES(610,'Spout Springs','OR',NULL,'US','US','United States',NULL,'OR','Oregon','None','None','["None"]','spout-springs',1,0);
INSERT INTO resort VALUES(611,'Warner Canyon','OR',NULL,'US','US','United States',NULL,'OR','Oregon','None','None','["None"]','warner-canyon',1,0);
INSERT INTO resort VALUES(612,'Badger Mountain','WA',NULL,'US','US','United States',NULL,'WA','Washington','None','None','["None"]','badger-mountain',1,0);
INSERT INTO resort VALUES(613,'Echo Valley','WA',NULL,'US','US','United States',NULL,'WA','Washington','None','None','["None"]','echo-valley',1,0);
INSERT INTO resort VALUES(614,'Hurricane Ridge','WA',NULL,'US','US','United States',NULL,'WA','Washington','None','None','["None"]','hurricane-ridge',1,0);
INSERT INTO resort VALUES(615,'Meany Lodge','WA',NULL,'US','US','United States',NULL,'WA','Washington','None','None','["None"]','meany-lodge',1,0);
INSERT INTO resort VALUES(616,'Sahalie Ski Club','WA',NULL,'US','US','United States',NULL,'WA','Washington','None','None','["None"]','sahalie-ski-club',1,0);
INSERT INTO resort VALUES(617,'Sitzmark Lifts','WA',NULL,'US','US','United States',NULL,'WA','Washington','None','None','["None"]','sitzmark-lifts',1,0);
INSERT INTO resort VALUES(618,'Alpental','WA',NULL,'US','US','United States',NULL,'WA','Washington','None','None','["None"]','alpental',1,0);
INSERT INTO resort VALUES(619,'Bear Valley','CA',NULL,'US','US','United States',NULL,'CA','California','None','None','["None"]','bear-valley',1,0);
INSERT INTO resort VALUES(620,'Blue Hills','MA',NULL,'US','US','United States',NULL,'MA','Massachusetts','None','None','["None"]','blue-hills',1,0);
INSERT INTO resort VALUES(621,'Elko Snobowl','NV',NULL,'US','US','United States',NULL,'NV','Nevada','None','None','["None"]','elko-snobowl',1,0);
INSERT INTO resort VALUES(622,'Sky Tavern','NV',NULL,'US','US','United States',NULL,'NV','Nevada','None','None','["None"]','sky-tavern',1,0);
INSERT INTO resort VALUES(623,'Summit','OR',NULL,'US','US','United States',NULL,'OR','Oregon','None','None','["None"]','summit',1,0);
INSERT INTO resort VALUES(624,'Leavenworth','WA',NULL,'US','US','United States',NULL,'WA','Washington','None','None','["None"]','leavenworth',1,0);
INSERT INTO resort VALUES(625,'Bluewood','WA',NULL,'US','US','United States',NULL,'WA','Washington','None','None','["None"]','bluewood',1,0);
INSERT INTO resort VALUES(626,'Brandywine','OH',NULL,'US','US','United States',NULL,'OH','Ohio','Epic','Epic','["Epic"]','brandywine',1,0);
INSERT INTO resort VALUES(627,'Mohawk Mountain','CT',NULL,'US','US','United States',NULL,'CT','Connecticut','None','None','["None"]','mohawk-mountain',1,0);
INSERT INTO resort VALUES(628,'Pebble Creek','ID',NULL,'US','US','United States',NULL,'ID','Idaho','None','None','["None"]','pebble-creek',1,0);
INSERT INTO resort VALUES(629,'Silver Mountain','ID',NULL,'US','US','United States',NULL,'ID','Idaho','None','None','["None"]','silver-mountain',1,0);
INSERT INTO resort VALUES(630,'Soldier Mountain','ID',NULL,'US','US','United States',NULL,'ID','Idaho','None','None','["None"]','soldier-mountain',1,0);
INSERT INTO resort VALUES(631,'Jiminy Peak','MA',NULL,'US','US','United States',NULL,'MA','Massachusetts','None','None','["None"]','jiminy-peak',1,0);
INSERT INTO resort VALUES(632,'Wachusett Mountain','MA',NULL,'US','US','United States',NULL,'MA','Massachusetts','None','None','["None"]','wachusett-mountain',1,0);
INSERT INTO resort VALUES(633,'Wisp Resort','MD',NULL,'US','US','United States',NULL,'MD','Maryland','None','None','["None"]','wisp-resort',1,0);
INSERT INTO resort VALUES(634,'Pajarito','NM',NULL,'US','US','United States',NULL,'NM','New Mexico','None','None','["None"]','pajarito',1,0);
INSERT INTO resort VALUES(635,'Bristol Mountain','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','bristol-mountain',1,0);
INSERT INTO resort VALUES(636,'Greek Peak','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','greek-peak',1,0);
INSERT INTO resort VALUES(637,'Holiday Valley','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','holiday-valley',1,0);
INSERT INTO resort VALUES(638,'Hoodoo','OR',NULL,'US','US','United States',NULL,'OR','Oregon','None','None','["None"]','hoodoo',1,0);
INSERT INTO resort VALUES(639,'Willamette Pass','OR',NULL,'US','US','United States',NULL,'OR','Oregon','None','None','["None"]','willamette-pass',1,0);
INSERT INTO resort VALUES(640,'Terry Peak','SD',NULL,'US','US','United States',NULL,'SD','South Dakota','None','None','["None"]','terry-peak',1,0);
INSERT INTO resort VALUES(641,'Ober Mountain','TN',NULL,'US','US','United States',NULL,'TN','Tennessee','None','None','["None"]','ober-mountain',1,0);
INSERT INTO resort VALUES(642,'Granite Peak','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','granite-peak',1,0);
INSERT INTO resort VALUES(643,'Timberline Mountain','WV',NULL,'US','US','United States',NULL,'WV','West Virginia','None','None','["None"]','timberline-mountain',1,0);
INSERT INTO resort VALUES(644,'Mount Southington','CT',NULL,'US','US','United States',NULL,'CT','Connecticut','None','None','["None"]','mount-southington',1,0);
INSERT INTO resort VALUES(645,'Ski Sundown','CT',NULL,'US','US','United States',NULL,'CT','Connecticut','None','None','["None"]','ski-sundown',1,0);
INSERT INTO resort VALUES(646,'Seven Oaks','IA',NULL,'US','US','United States',NULL,'IA','Iowa','None','None','["None"]','seven-oaks',1,0);
INSERT INTO resort VALUES(647,'Sundown Mountain','IA',NULL,'US','US','United States',NULL,'IA','Iowa','None','None','["None"]','sundown-mountain',1,0);
INSERT INTO resort VALUES(648,'Kelly Canyon','ID',NULL,'US','US','United States',NULL,'ID','Idaho','None','None','["None"]','kelly-canyon',1,0);
INSERT INTO resort VALUES(649,'Ski Butternut','MA',NULL,'US','US','United States',NULL,'MA','Massachusetts','None','None','["None"]','ski-butternut',1,0);
INSERT INTO resort VALUES(650,'Brundage','ID',NULL,'US','US','United States',NULL,'ID','Idaho','None','None','["None"]','brundage',1,0);
INSERT INTO resort VALUES(651,'Big Rock','ME',NULL,'US','US','United States',NULL,'ME','Maine','None','None','["None"]','big-rock',1,0);
INSERT INTO resort VALUES(652,'Camden Snow Bowl','ME',NULL,'US','US','United States',NULL,'ME','Maine','None','None','["None"]','camden-snow-bowl',1,0);
INSERT INTO resort VALUES(653,'Lost Valley','ME',NULL,'US','US','United States',NULL,'ME','Maine','None','None','["None"]','lost-valley',1,0);
INSERT INTO resort VALUES(654,'King Pine','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','king-pine',1,0);
INSERT INTO resort VALUES(655,'Pats Peak','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','pats-peak',1,0);
INSERT INTO resort VALUES(656,'Ragged Mountain','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','ragged-mountain',1,0);
INSERT INTO resort VALUES(657,'Welch Village','MN',NULL,'US','US','United States',NULL,'MN','Minnesota','None','None','["None"]','welch-village',1,0);
INSERT INTO resort VALUES(658,'Ski Apache','NM',NULL,'US','US','United States',NULL,'NM','New Mexico','None','None','["None"]','ski-apache',1,0);
INSERT INTO resort VALUES(659,'Lee Canyon','NV',NULL,'US','US','United States',NULL,'NV','Nevada','None','None','["None"]','lee-canyon',1,0);
INSERT INTO resort VALUES(660,'Holimont','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','holimont',1,0);
INSERT INTO resort VALUES(661,'Peek''n Peak','NY',NULL,'US','US','United States',NULL,'NY','New York','None','None','["None"]','peek-n-peak',1,0);
INSERT INTO resort VALUES(662,'Discovery Ski Area','MT',NULL,'US','US','United States',NULL,'MT','Montana','None','None','["None"]','discovery-ski-area',1,0);
INSERT INTO resort VALUES(663,'Ski Bowl','OR',NULL,'US','US','United States',NULL,'OR','Oregon','None','None','["None"]','ski-bowl',1,0);
INSERT INTO resort VALUES(664,'Lost Trail','MT',NULL,'US','US','United States',NULL,'MT','Montana','None','None','["None"]','lost-trail',1,0);
INSERT INTO resort VALUES(665,'Appalachian Ski Mountain','NC',NULL,'US','US','United States',NULL,'NC','North Carolina','None','None','["None"]','appalachian-ski-mountain',1,0);
INSERT INTO resort VALUES(666,'Beech Mountain','NC',NULL,'US','US','United States',NULL,'NC','North Carolina','None','None','["None"]','beech-mountain',1,0);
INSERT INTO resort VALUES(667,'Elk Mountain','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','None','None','["None"]','elk-mountain',1,0);
INSERT INTO resort VALUES(668,'Sugar Mountain','NC',NULL,'US','US','United States',NULL,'NC','North Carolina','None','None','["None"]','sugar-mountain',1,0);
INSERT INTO resort VALUES(669,'Shawnee Mountain','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','None','None','["None"]','shawnee-mountain',1,0);
INSERT INTO resort VALUES(670,'Huff Hills','ND',NULL,'US','US','United States',NULL,'ND','North Dakota','None','None','["None"]','huff-hills',1,0);
INSERT INTO resort VALUES(671,'Loup Loup','WA',NULL,'US','US','United States',NULL,'WA','Washington','None','None','["None"]','loup-loup',1,0);
INSERT INTO resort VALUES(672,'Massanutten','VA',NULL,'US','US','United States',NULL,'VA','Virginia','None','None','["None"]','massanutten',1,0);
INSERT INTO resort VALUES(673,'Mt. Spokane','WA',NULL,'US','US','United States',NULL,'WA','Washington','None','None','["None"]','mt-spokane',1,0);
INSERT INTO resort VALUES(674,'Whitecap Mountain','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','whitecap-mountain',1,0);
INSERT INTO resort VALUES(675,'Canaan Valley','WV',NULL,'US','US','United States',NULL,'WV','West Virginia','None','None','["None"]','canaan-valley',1,0);
INSERT INTO resort VALUES(676,'Winterplace','WV',NULL,'US','US','United States',NULL,'WV','West Virginia','None','None','["None"]','winterplace',1,0);
INSERT INTO resort VALUES(677,'Hogadon','WY',NULL,'US','US','United States',NULL,'WY','Wyoming','None','None','["None"]','hogadon',1,0);
INSERT INTO resort VALUES(678,'Cascade Mountain','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','cascade-mountain',1,0);
INSERT INTO resort VALUES(679,'White Pine','WY',NULL,'US','US','United States',NULL,'WY','Wyoming','None','None','["None"]','white-pine',1,0);
INSERT INTO resort VALUES(680,'Sunrise Park','AZ',NULL,'US','US','United States',NULL,'AZ','Arizona','None','None','["None"]','sunrise-park',1,0);
INSERT INTO resort VALUES(681,'Devil''s Head','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','None','None','["None"]','devil-s-head',1,0);
INSERT INTO resort VALUES(682,'Meadowlark','WY',NULL,'US','US','United States',NULL,'WY','Wyoming','None','None','["None"]','meadowlark',1,0);
INSERT INTO resort VALUES(683,'Mount Baker','WA',NULL,'US','US','United States',NULL,'WA','Washington','None','None','["None"]','mount-baker',1,0);
INSERT INTO resort VALUES(684,'Blue Mountain','ON',NULL,'CA','CA','Canada',NULL,'ON','Ontario','Ikon','Ikon','["Ikon"]','blue-mountain-on',1,0);
INSERT INTO resort VALUES(685,'Holiday Mountain','MB',NULL,'CA','CA','Canada',NULL,'MB','Manitoba','None','None','["None"]','holiday-mountain-mb',1,0);
INSERT INTO resort VALUES(686,'Trysil','Norway',NULL,'NO','NO','Norway',NULL,'Norway','Norway','Epic','Epic','["Epic"]','trysil-norway',1,0);
INSERT INTO resort VALUES(687,'Hemsedal','Norway',NULL,'NO','NO','Norway',NULL,'Norway','Norway','Epic','Epic','["Epic"]','hemsedal-norway',1,0);
INSERT INTO resort VALUES(688,'Baqueira Beret','Pyrenees',NULL,'ES','ES','Spain',NULL,'Pyrenees','Pyrenees','None','None','["None"]','baqueira-beret-pyrenees',1,0);
INSERT INTO resort VALUES(689,'Astun','Pyrenees',NULL,'ES','ES','Spain',NULL,'Pyrenees','Pyrenees','None','None','["None"]','astun-pyrenees',1,0);
INSERT INTO resort VALUES(690,'Candanchu','Pyrenees',NULL,'ES','ES','Spain',NULL,'Pyrenees','Pyrenees','None','None','["None"]','candanchu-pyrenees',1,0);
INSERT INTO resort VALUES(691,'Are','Jamtland',NULL,'SE','SE','Sweden',NULL,'Jamtland','Jamtland','None','None','["None"]','are-jamtland',1,0);
INSERT INTO resort VALUES(692,'Lookout Pass','ID',NULL,'US','US','United States',NULL,'ID','Idaho','None','None','["None"]','lookout-pass-id',1,0);
INSERT INTO resort VALUES(693,'Mt. Crescent','NE',NULL,'US','US','United States',NULL,'NE','Nebraska','None','None','["None"]','mt-crescent-ne',1,0);
INSERT INTO resort VALUES(694,'Hidden Valley','PA',NULL,'US','US','United States',NULL,'PA','Pennsylvania','Epic','Epic','["Epic"]','hidden-valley-pa',1,0);
INSERT INTO resort VALUES(695,'Crystal Mountain','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','crystal-mountain-mi-2',1,0);
INSERT INTO resort VALUES(696,'Magic Mountain','VT',NULL,'US','US','United States',NULL,'VT','Vermont','Indy','Indy','["Indy"]','magic-mountain-vt',1,0);
INSERT INTO resort VALUES(697,'Alpine Valley','WI',NULL,'US','US','United States',NULL,'WI','Wisconsin','Epic','Epic','["Epic"]','alpine-valley-wi',1,0);
INSERT INTO resort VALUES(698,'The Homestead','VA',NULL,'US','US','United States',NULL,'VA','Virginia','None','None','["None"]','the-homestead-va',1,0);
INSERT INTO resort VALUES(699,'Crystal Mountain','WA',NULL,'US','US','United States',NULL,'WA','Washington','Ikon','Ikon','["Ikon"]','crystal-mountain-wa',1,0);
INSERT INTO resort VALUES(700,'Diamond Peak','CA',NULL,'US','US','United States',NULL,'CA','California','None','None','["None"]','diamond-peak-ca',1,0);
INSERT INTO resort VALUES(701,'Hidden Valley','MO',NULL,'US','US','United States',NULL,'MO','Missouri','Epic','Epic','["Epic"]','hidden-valley-mo',1,0);
INSERT INTO resort VALUES(702,'Powder Ridge','CT',NULL,'US','US','United States',NULL,'CT','Connecticut','None','None','["None"]','powder-ridge-ct',1,0);
INSERT INTO resort VALUES(703,'Black Mountain','NH',NULL,'US','US','United States',NULL,'NH','New Hampshire','None','None','["None"]','black-mountain-nh',1,0);
INSERT INTO resort VALUES(704,'Alpine Valley','MI',NULL,'US','US','United States',NULL,'MI','Michigan','None','None','["None"]','alpine-valley-mi',1,0);
INSERT INTO resort VALUES(705,'Snow Creek','MO',NULL,'US','US','United States',NULL,'MO','Missouri','None','None','["None"]','snow-creek-mo',1,0);
CREATE TABLE user (
	id INTEGER NOT NULL, 
	first_name VARCHAR(80) NOT NULL, 
	last_name VARCHAR(80) NOT NULL, 
	email VARCHAR(120) NOT NULL, 
	password_hash VARCHAR(256) NOT NULL, 
	rider_type VARCHAR(50), 
	primary_rider_type VARCHAR(50), 
	secondary_rider_types JSON, 
	rider_types JSON, 
	pass_type VARCHAR(100), 
	profile_setup_complete BOOLEAN, 
	gender VARCHAR(20), 
	birth_year INTEGER, 
	home_state VARCHAR(50), 
	skill_level VARCHAR(50), 
	gear VARCHAR(200), 
	home_mountain VARCHAR(100), 
	mountains_visited JSON, 
	home_resort_id INTEGER, 
	visited_resort_ids JSON, 
	open_dates JSON, 
	wish_list_resorts JSON, 
	terrain_preferences JSON, 
	equipment_status VARCHAR(20), 
	buddy_passes JSON, 
	buddy_passes_available BOOLEAN DEFAULT 'true' NOT NULL, 
	created_at DATETIME, 
	last_active_at DATETIME, 
	lifecycle_stage VARCHAR(20), 
	onboarding_completed_at DATETIME, 
	profile_completed_at DATETIME, 
	first_connection_at DATETIME, 
	first_trip_created_at DATETIME, 
	is_seeded BOOLEAN, 
	invited_by_user_id INTEGER, 
	email_opt_in BOOLEAN, 
	email_transactional BOOLEAN, 
	email_social BOOLEAN, 
	email_digest BOOLEAN, 
	timezone VARCHAR(50), 
	login_count INTEGER, 
	first_planning_timestamp DATETIME, 
	planning_completed_timestamp DATETIME, 
	planning_dismissed_timestamp DATETIME, 
	historical_passes_by_season JSON, 
	primary_riding_style VARCHAR(50), 
	welcome_modal_seen_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (email), 
	FOREIGN KEY(home_resort_id) REFERENCES resort (id), 
	FOREIGN KEY(invited_by_user_id) REFERENCES user (id)
);
INSERT INTO user VALUES(1,'Richard','Test1','test1@gmail.com','scrypt:32768:8:1$1FXajHBN0ViQQDQA$cdf55fab259698d4f6e17a4c87f60af6e2798e6c359985e614c122f24fe63ffd758c58d7af8516c32f15a0e48e94735124f9840bdee612d31709bd0d9325e45f',NULL,NULL,'[]','["Skier"]','Epic',0,NULL,NULL,'CO','Beginner',NULL,NULL,'["Chapelco", "Cerro Catedral"]',NULL,'[120, 119]','[]','[119, 128]','[]','have_own_equipment','{}',1,NULL,NULL,'new',NULL,NULL,NULL,NULL,0,NULL,1,1,0,0,NULL,0,NULL,NULL,NULL,'{}',NULL,NULL);
INSERT INTO user VALUES(2,'Richard','Battle-Baxter','richardbattlebaxter@gmail.com','scrypt:32768:8:1$e025cSrRMls9pwLm$9199f0a3b09d4a264b07133a237f602e015bc151b6db4e32d45cbf7c8240ae70d1c5c7baff47394bd03888c28405ff6abd025dbdbe7df9547b6303c2a109ee0e',NULL,'Skier','[]','[]','Epic',0,NULL,1985,'Colorado','Advanced',NULL,NULL,'[]',NULL,'[]','[]','[]','[]','have_own_equipment','{}',1,NULL,NULL,'new',NULL,NULL,NULL,NULL,0,NULL,1,1,0,0,NULL,0,NULL,NULL,NULL,'{}',NULL,NULL);
INSERT INTO user VALUES(3,'Taylor','DevTest','testfriend.devonly@baselodge.dev','scrypt:32768:8:1$pMKL3hvbhbycOxZq$c6551b35780f6d1767677fa976567549d66d2fd2f9ce5e29975c71917b7539c26e54f1dc41aa9ae7fd7f6d058b9286c1baf076af209a4d2a2355d8e91eb8827e',NULL,'Skier','[]','["Skier"]','Epic',0,NULL,1990,'CO','Advanced',NULL,NULL,'[]',NULL,'[]','[]','[]','[]','have_own_equipment','{}',1,'2026-04-10 04:21:31.345003',NULL,'active',NULL,NULL,NULL,NULL,1,NULL,1,1,0,0,NULL,3,'2026-04-10 04:21:31.345006',NULL,NULL,'{}',NULL,NULL);
CREATE TABLE ski_trip (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	resort_id INTEGER, 
	state VARCHAR(50), 
	mountain VARCHAR(100), 
	start_date DATE, 
	end_date DATE, 
	pass_type VARCHAR(50), 
	is_public BOOLEAN, 
	ride_intent VARCHAR(20), 
	trip_duration VARCHAR(20), 
	trip_equipment_status VARCHAR(20), 
	equipment_override VARCHAR(20), 
	accommodation_status VARCHAR(20), 
	accommodation_link VARCHAR(500), 
	max_participants INTEGER, 
	created_at DATETIME, 
	is_group_trip BOOLEAN, 
	created_by_user_id INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user (id), 
	FOREIGN KEY(resort_id) REFERENCES resort (id), 
	FOREIGN KEY(created_by_user_id) REFERENCES user (id)
);
INSERT INTO ski_trip VALUES(1,1,5,'CO','Beaver Creek','2026-04-10','2026-04-11','No Pass',1,NULL,'one_night',NULL,NULL,NULL,NULL,NULL,'2026-04-09 06:59:12.982727',0,1);
INSERT INTO ski_trip VALUES(2,1,6,'CO','Breckenridge','2026-04-16','2026-04-18','No Pass',1,NULL,'two_nights',NULL,NULL,NULL,NULL,NULL,'2026-04-10 04:16:06.503499',0,1);
INSERT INTO ski_trip VALUES(3,3,NULL,'CO','Vail','2026-05-25','2026-05-28','Epic',1,NULL,'three_plus_nights',NULL,NULL,NULL,NULL,NULL,'2026-04-10 04:21:31.453575',1,NULL);
INSERT INTO ski_trip VALUES(4,2,NULL,'CO','Vail','2026-05-26','2026-05-28','Epic',1,NULL,'two_nights',NULL,NULL,NULL,NULL,NULL,'2026-04-10 04:21:31.460588',0,NULL);
CREATE TABLE friend (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	friend_id INTEGER NOT NULL, 
	created_at DATETIME, 
	is_seeded BOOLEAN, 
	trip_invites_allowed BOOLEAN, 
	PRIMARY KEY (id), 
	CONSTRAINT unique_friendship UNIQUE (user_id, friend_id), 
	FOREIGN KEY(user_id) REFERENCES user (id), 
	FOREIGN KEY(friend_id) REFERENCES user (id)
);
INSERT INTO friend VALUES(1,2,3,'2026-04-10 04:21:31.449053',1,0);
INSERT INTO friend VALUES(2,3,2,'2026-04-10 04:21:31.451296',1,0);
CREATE TABLE invite_token (
	id INTEGER NOT NULL, 
	token VARCHAR(64) NOT NULL, 
	inviter_id INTEGER NOT NULL, 
	created_at DATETIME, 
	expires_at DATETIME, 
	used_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(inviter_id) REFERENCES user (id)
);
INSERT INTO invite_token VALUES(1,'_pUb5JmYMq7p8t2Yxbf80Q',1,'2026-04-09 04:06:33.248203','2026-04-11 04:06:33.247073',NULL);
INSERT INTO invite_token VALUES(2,'cB50WCQr-XexqOyWhviYZw',2,'2026-04-10 02:00:07.656462','2026-04-12 02:00:07.655179',NULL);
CREATE TABLE group_trip (
	id INTEGER NOT NULL, 
	host_id INTEGER NOT NULL, 
	title VARCHAR(200), 
	start_date DATE NOT NULL, 
	end_date DATE NOT NULL, 
	accommodation_status VARCHAR(20), 
	transportation_status VARCHAR(14), 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(host_id) REFERENCES user (id), 
	CONSTRAINT accommodation_status_enum CHECK (accommodation_status IN ('BOOKED', 'NOT_YET', 'STAYING_WITH_FRIENDS')), 
	CONSTRAINT transportation_status_enum CHECK (transportation_status IN ('HAVE_TRANSPORT', 'NEED_TRANSPORT', 'NOT_SURE'))
);
CREATE TABLE equipment_setup (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	slot VARCHAR(9), 
	discipline VARCHAR(11), 
	brand VARCHAR(100), 
	model VARCHAR(100), 
	length_cm INTEGER, 
	width_mm INTEGER, 
	binding_type VARCHAR(50), 
	boot_brand VARCHAR(50), 
	boot_model VARCHAR(100), 
	boot_flex INTEGER, 
	purchase_year INTEGER, 
	equipment_status VARCHAR(20), 
	is_active BOOLEAN, 
	PRIMARY KEY (id), 
	CONSTRAINT unique_user_equipment_slot UNIQUE (user_id, slot), 
	FOREIGN KEY(user_id) REFERENCES user (id), 
	CONSTRAINT equipment_slot_enum CHECK (slot IN ('PRIMARY', 'SECONDARY')), 
	CONSTRAINT equipment_discipline_enum CHECK (discipline IN ('SKIER', 'SNOWBOARDER'))
);
CREATE TABLE dismissed_nudge (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	date_range_start DATE NOT NULL, 
	date_range_end DATE NOT NULL, 
	dismissed_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT unique_dismissed_nudge UNIQUE (user_id, date_range_start, date_range_end), 
	FOREIGN KEY(user_id) REFERENCES user (id)
);
CREATE TABLE event (
	id INTEGER NOT NULL, 
	event_name VARCHAR(100) NOT NULL, 
	user_id INTEGER NOT NULL, 
	payload JSON, 
	created_at DATETIME, 
	environment VARCHAR(10), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user (id)
);
CREATE TABLE activity (
	id INTEGER NOT NULL, 
	actor_user_id INTEGER NOT NULL, 
	recipient_user_id INTEGER NOT NULL, 
	type VARCHAR(50) NOT NULL, 
	object_type VARCHAR(20) NOT NULL, 
	object_id INTEGER NOT NULL, 
	created_at DATETIME, 
	extra_data JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actor_user_id) REFERENCES user (id), 
	FOREIGN KEY(recipient_user_id) REFERENCES user (id)
);
INSERT INTO activity VALUES(1,2,3,'trip_invite_accepted','trip',3,'2026-04-10 04:23:50.811660',NULL);
INSERT INTO activity VALUES(2,2,3,'friend_joined_trip','trip',3,'2026-04-10 04:23:50.815982',NULL);
CREATE TABLE ski_trip_participant (
	id INTEGER NOT NULL, 
	trip_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	status VARCHAR(8) NOT NULL, 
	role VARCHAR(5) NOT NULL, 
	transportation_status VARCHAR(7), 
	equipment_status VARCHAR(13), 
	taking_lesson VARCHAR(5) DEFAULT 'no' NOT NULL, 
	carpool_role VARCHAR(17), 
	carpool_seats INTEGER, 
	needs_ride BOOLEAN, 
	start_date DATE, 
	end_date DATE, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT unique_ski_trip_participant UNIQUE (trip_id, user_id), 
	FOREIGN KEY(trip_id) REFERENCES ski_trip (id), 
	FOREIGN KEY(user_id) REFERENCES user (id), 
	CONSTRAINT ski_trip_participant_status_enum CHECK (status IN ('INVITED', 'ACCEPTED', 'DECLINED')), 
	CONSTRAINT participant_role_enum CHECK (role IN ('OWNER', 'GUEST')), 
	CONSTRAINT participant_transportation_enum CHECK (transportation_status IN ('DRIVING', 'FLYING', 'TRAIN', 'BUS', 'TBD')), 
	CONSTRAINT participant_equipment_enum CHECK (equipment_status IN ('OWN', 'RENTING', 'NEEDS_RENTALS')), 
	CONSTRAINT lesson_choice_enum CHECK (taking_lesson IN ('yes', 'no', 'maybe')), 
	CONSTRAINT carpool_role_enum CHECK (carpool_role IN ('DRIVER', 'RIDER', 'DRIVER_WITH_SPACE', 'DRIVER_NO_SPACE', 'NEEDS_RIDE', 'NOT_CARPOOLING', 'OTHER'))
);
INSERT INTO ski_trip_participant VALUES(1,1,1,'ACCEPTED','OWNER',NULL,NULL,'no',NULL,NULL,NULL,NULL,NULL,'2026-04-09 06:59:12.986965');
INSERT INTO ski_trip_participant VALUES(2,2,1,'ACCEPTED','OWNER',NULL,NULL,'no',NULL,NULL,NULL,NULL,NULL,'2026-04-10 04:16:06.511055');
INSERT INTO ski_trip_participant VALUES(3,3,3,'ACCEPTED','OWNER',NULL,NULL,'no',NULL,NULL,NULL,NULL,NULL,'2026-04-10 04:21:31.457787');
INSERT INTO ski_trip_participant VALUES(4,3,2,'ACCEPTED','GUEST',NULL,NULL,'no',NULL,NULL,NULL,NULL,NULL,'2026-04-10 04:21:31.460018');
CREATE TABLE invitation (
	id INTEGER NOT NULL, 
	sender_id INTEGER NOT NULL, 
	receiver_id INTEGER NOT NULL, 
	trip_id INTEGER, 
	invite_type VARCHAR(8) DEFAULT 'outbound' NOT NULL, 
	status VARCHAR(20), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT unique_invitation_per_trip UNIQUE (sender_id, receiver_id, trip_id), 
	FOREIGN KEY(sender_id) REFERENCES user (id), 
	FOREIGN KEY(receiver_id) REFERENCES user (id), 
	FOREIGN KEY(trip_id) REFERENCES ski_trip (id), 
	CONSTRAINT invite_type_enum CHECK (invite_type IN ('OUTBOUND', 'REQUEST'))
);
CREATE TABLE trip_guest (
	id INTEGER NOT NULL, 
	trip_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	status VARCHAR(8) NOT NULL, 
	joined_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT unique_trip_guest UNIQUE (trip_id, user_id), 
	FOREIGN KEY(trip_id) REFERENCES group_trip (id), 
	FOREIGN KEY(user_id) REFERENCES user (id), 
	CONSTRAINT guest_status_enum CHECK (status IN ('INVITED', 'ACCEPTED', 'DECLINED'))
);
CREATE TABLE email_log (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	email_type VARCHAR(100) NOT NULL, 
	source_event_id INTEGER, 
	sent_at DATETIME, 
	send_count INTEGER, 
	environment VARCHAR(10), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user (id), 
	FOREIGN KEY(source_event_id) REFERENCES event (id)
);
CREATE UNIQUE INDEX ix_invite_token_token ON invite_token (token);
COMMIT;
