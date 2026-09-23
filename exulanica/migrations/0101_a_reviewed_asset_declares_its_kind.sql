-- 0101_a_reviewed_asset_declares_its_kind.sql
-- Every reviewed asset states what it is for, so only an object can be placed as one.
--
-- world_reviewed_asset holds every reviewed container a catalog publishes: the three generated
-- marker meshes 0042 seeded, which a person places as authored objects, and, through the reviewed
-- import boundary (0054, exulanica/world/asset_import.py), the bodies, worn parts and material
-- packs the character catalogs publish, because the character renderer fetches them by key from
-- the same authenticated registry. Without a kind on the row, the object chooser listed every
-- character container as something to place and add_object accepted one.
--
-- kind is declared by whoever publishes a row and never defaulted: the column has no default and
-- import_reviewed_asset requires one. exulanica/world/asset_kinds.py is the registry of kinds and
-- says what each permits: an object may be placed, a component may not. The CHECK below restates
-- its kinds, and tests/test_reviewed_asset_placeability.py holds the two equal on the live schema.
--
-- The backfill allows; it does not default. A row becomes an object only when it is one of the
-- (asset_key, content_sha256) pairs 0042 pinned, and a component only when it is one of the 160
-- pairs named by the committed versions of the character import manifests,
-- assets/characters/makehuman-people-v1/imports.json and
-- assets/characters/quaternius-modular-v2/*.import.json (13 file versions across 10 commits).
-- Any other row stops the migration and is named in the error, because nothing in the database
-- says what an asset outside those catalogs is for, and a guess here would decide what a person
-- may place. The migration reads nothing outside the database.
--
-- An object that already holds a component keeps it. The foreign key from world_alternate_object
-- to content_sha256 is untouched, so a version that holds one reads, draws and edits as before;
-- only placing a component is refused, by the application.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_reviewed_asset add column kind text;

-- The three generated marker meshes, exactly as 0042 pinned them.
update world_reviewed_asset set kind = 'object'
where (asset_key, content_sha256) in (values
  ('cc0.marker-cube', 'b41289ac10548cf698d46a15206caa8e744b0b800f4ac29260c99f18d8b831d9'),
  ('cc0.marker-pillar', 'b960af0f1c85f6c41a38ce09727cd19bc2bbc0e21bb8f3f111707af9b90b2737'),
  ('cc0.marker-plate', '19425a058c19d4009392093e770c7f115a68d020b67e0bdce83abdad4b5a2f6e')
);

-- Every pair a committed character import manifest has named.
update world_reviewed_asset set kind = 'component'
where (asset_key, content_sha256) in (values
  ('makehuman.people.feminine.base.v1', 'e6c31847a6df176eea18552bb03361b1044eb4607529136c4290cb750dcf002d'),
  ('makehuman.people.feminine.base.v2', 'dc2e7058e2ac4b184073e504cd019d996cea7c5aaef0ae2d11730e8f1630b69c'),
  ('makehuman.people.feminine.hair.afro01.v1', '50420f8e6d68f5844f7e7aefb9e420db466b5d729477e59d4124b20cee168ad8'),
  ('makehuman.people.feminine.hair.afro01.v2', 'e39e86d0b03ca7956a0bb9cebba5602c4f11e85a25e549e7cf04e66654492444'),
  ('makehuman.people.feminine.hair.bob01.v1', '7c0783eb06c0cf448ace489c0b2bef9f86fe480ce1a5fd8894d77232b00c246c'),
  ('makehuman.people.feminine.hair.bob01.v2', 'f96aeed6bae76ea585323f7f292abffda9beee1aa6bbe75e0c5dd5980255445a'),
  ('makehuman.people.feminine.hair.bob02.v1', 'fc21f36a5c997f1ef23792cd161adb51ef13f69aaf7068db023ee4e37c6209d2'),
  ('makehuman.people.feminine.hair.bob02.v2', '853b904a8d98814ab8f32492deb033de5ad8420bb30989006d835fbcc4124a28'),
  ('makehuman.people.feminine.hair.braid01.v1', 'bcf02a29595358d93ff5e08c50aad837e863c48a4436122d7ecfc3ce35011c3b'),
  ('makehuman.people.feminine.hair.braid01.v2', '62cb8f0acd233ba61ed1a493c214ace960e15448ef7b024becdf9374e6ebff6e'),
  ('makehuman.people.feminine.hair.long01.v1', '65d236812c110ce4f5be9e91dd537c27ea99eeaaf581a38be02deb7d7cff5276'),
  ('makehuman.people.feminine.hair.long01.v2', 'f12d7b5ca22d46fcb9e07637bafcc37d4b4629f06c14883c5754919f09f6d902'),
  ('makehuman.people.feminine.hair.ponytail01.v1', '3a9334a7f943eff47bd4c1e20cb2cb28ab63b58f0e982325826e58bfa0b4f0e1'),
  ('makehuman.people.feminine.hair.ponytail01.v2', '9fa94687878dcdfef0ca2ed13fb582a5d85038966c77f1c06a0b9c1a25370383'),
  ('makehuman.people.feminine.hair.short02.v1', '33e228a08bba8dc9a634bf2c46fdc1ba30917d6c3c1f7d1128b712bb430bc243'),
  ('makehuman.people.feminine.hair.short02.v2', '6532a11a083ed35965682e6aad7b8ba217ea162543ffde7567ff975fc0fd46eb'),
  ('makehuman.people.feminine.outfit.female-casualsuit01.v1', '2143182c9709e2bfee4ca8e309f4c65b27a52bad97e8c25cf8fc6b4620d416ef'),
  ('makehuman.people.feminine.outfit.female-casualsuit01.v2', 'c939c626d17bb23a1b6cc54fbfe4ddede781c918f6356d734e9368251595ced4'),
  ('makehuman.people.feminine.outfit.female-casualsuit02.v1', '364327d084c5493c2e06877720ac2c15d1edd7cbb0b47176764de98250fe07b8'),
  ('makehuman.people.feminine.outfit.female-casualsuit02.v2', '34e27c57b1360003fa84a9e1bfa51d68b393dd2b4344a67571b0cae6af91fe8d'),
  ('makehuman.people.feminine.outfit.female-elegantsuit01.v1', '5c96cafd3bf491e76d4b235916c739ad20592644a8dff16d03413d1baae38263'),
  ('makehuman.people.feminine.outfit.female-elegantsuit01.v2', '49c51d3d07690f85abb1ad246ad477fbb6eae305a30d4b15eec142b6a581b168'),
  ('makehuman.people.feminine.outfit.female-sportsuit01.v1', '3e65d51b8d42fc9d17280c7a3361321ec125174614815e63e37f06bfa9ab44a0'),
  ('makehuman.people.feminine.outfit.female-sportsuit01.v2', '815b25f7961b8fe3f9ba3e035c8c22cc2da7adc0761cfcf7de9666b31976a985'),
  ('makehuman.people.feminine.outfit.male-casualsuit01.v1', '986dd6449bf0556e2cbe29be8b12f94b0ca3c91733713f857643e11520384013'),
  ('makehuman.people.feminine.outfit.male-casualsuit01.v2', '0861f4396f4d45796797ce1c6a1283abaa0b9b7e9615d235f5d8258435873e48'),
  ('makehuman.people.feminine.outfit.male-casualsuit03.v1', 'e0bddbb1fa4a5322be2da76a47bb15c782bc4fd5c3df9161a7ee3d5d689ff6c6'),
  ('makehuman.people.feminine.outfit.male-casualsuit03.v2', '7cf62b4245b272c3d0082e38f7e4a5ab8ed10bb76558144bd122d0ae62fb226d'),
  ('makehuman.people.feminine.outfit.male-casualsuit05.v1', 'b3addf8aa6b5c89f08543ee40953cf71fd1da0b2881c8901827a13844ef9432c'),
  ('makehuman.people.feminine.outfit.male-casualsuit05.v2', '20ce858c2701853bdf245f1379406774142efeb12deaf100c3c374597e8a73ff'),
  ('makehuman.people.feminine.outfit.male-casualsuit06.v1', '7a221bf21f793f0a684b4467b3bdc89c474e51aa6d8acf8c034f66add3ccab19'),
  ('makehuman.people.feminine.outfit.male-casualsuit06.v2', '139da5daf46bfc8d077d3fe1e1b54f2111a7d87fdef5f5cca8420f130dbb66c5'),
  ('makehuman.people.feminine.shoes.shoes01.v1', '9111c427d29fc1a038156f4d26d84d31e5278567c47558f0990304d6d0153eaf'),
  ('makehuman.people.feminine.shoes.shoes01.v2', 'd73de156ea3c9dfd249d94cf42e0637dbf965f989d741029488c7b7db713fe06'),
  ('makehuman.people.feminine.shoes.shoes02.v1', 'e5884273ccb98ee4d06a53e4563635c17c3b12dd31802197e267bd70f21a72c4'),
  ('makehuman.people.feminine.shoes.shoes02.v2', 'ab2e7ee9a355a4fb40fda77d8fb8736fd95ae58491113bc61a69e45d8a9d18f5'),
  ('makehuman.people.feminine.shoes.shoes03.v1', 'b1780b4fdc86736c7bd37e85a10619e8737ed6067a348ded85b15bec5c35ac73'),
  ('makehuman.people.feminine.shoes.shoes03.v2', 'be8234e052b38d80b2b852777b250dce1fa18ecc56ff391273040596d105c071'),
  ('makehuman.people.feminine.shoes.shoes04.v1', '498f227f128a80e965f2052b198369cd3a151e46bad073716c6127d7798ae470'),
  ('makehuman.people.feminine.shoes.shoes04.v2', '191ca8627cfc5ffc58a3da98b2792c4cdf0a78252f67f5b7b053636ae7e9bb21'),
  ('makehuman.people.feminine.shoes.shoes05.v1', '1f89ae677497f0328d6c24da82903bac8f8f427ca26650905f6c16fc14a38c69'),
  ('makehuman.people.feminine.shoes.shoes05.v2', '8551b29010049e99af073f367ae6446d9e4ca8dcaf8fd9493b1ff35bf2afec66'),
  ('makehuman.people.feminine.shoes.shoes06.v1', '6d04c0a9b0584c73b1c54841bcb5fbc7b12c119ce7e3142bff0223fa3bf102bc'),
  ('makehuman.people.feminine.shoes.shoes06.v2', '7bee6559f6a07c1f538e0315ca6efdde712713cc7174540d4be0b1271bd00419'),
  ('makehuman.people.masculine.base.v1', '9badd953adf405c3cb75c4caeab30236749ecd3b46979d0765180693c727e5fb'),
  ('makehuman.people.masculine.base.v2', '1f5e7df604d74dcd69341cb11d8b8a71d266ad812ce0950b2a69201e1250ab5a'),
  ('makehuman.people.masculine.hair.afro01.v1', '72a0678cc3ccf2d8b89cb0d90a796516e069d0c0d373b43cbececcedc1941893'),
  ('makehuman.people.masculine.hair.afro01.v2', '8974206c0a867646c4f1f69fd2fb1b54e0fdfd716150ade916e4f534c6e0df75'),
  ('makehuman.people.masculine.hair.short01.v1', '347584fc3bc4dd1cd1688a087fbe40f5795c49eab9ad0c57c7c53408c3010a0e'),
  ('makehuman.people.masculine.hair.short01.v2', 'd9745597550b6c29ebd664a1a2db243203df61fb6865627ad7ad63e57a8a4bd7'),
  ('makehuman.people.masculine.hair.short02.v1', '0354620b5bf5380f353e97aebffa9ab67e5a6d69e8469658bcc500edae0f9bf3'),
  ('makehuman.people.masculine.hair.short02.v2', 'e5747b741ad2db468cc290b6757d049c7edb4af79995b81d14561548c508aa4a'),
  ('makehuman.people.masculine.hair.short03.v1', '9add51377a8f0f9cc6a436534fb42ab596595779c23e273c8ba26cbcdf1f1bfa'),
  ('makehuman.people.masculine.hair.short03.v2', '9de0ad0d0f96a6b16e6f3e00857842c9fb3d593f789fdb08a6e278165ee908b4'),
  ('makehuman.people.masculine.hair.short04.v1', '7e88076b1fd35d491cadaf8ea4f70e45db047973adc3c6120dba72db6f62ddce'),
  ('makehuman.people.masculine.hair.short04.v2', '679fb95bf39302195137f9dc2a4f56751e39ce4cbc7d44ade28a0f6b15d3df12'),
  ('makehuman.people.masculine.outfit.male-casualsuit01.v1', '89ccd65e371ec7b58c28c4ca3cd576b903fceda44929a62a7c8bdbfe63694d7d'),
  ('makehuman.people.masculine.outfit.male-casualsuit01.v2', 'd0b57f4083edc7c008a269372d79e6cec2613b2472756e7f9c0d25e7de07589b'),
  ('makehuman.people.masculine.outfit.male-casualsuit02.v1', '39f026485d47d2b6080e6ee072fde1b4ebd357337a862f0e111855476ed676bf'),
  ('makehuman.people.masculine.outfit.male-casualsuit02.v2', '2311f0ab988c65cdd525a64949c6d56a28cf6622df64310c19d34d8e9a4f12da'),
  ('makehuman.people.masculine.outfit.male-casualsuit03.v1', '229637eecd5c4c3c053accb00e47fec838ec921d01338ab310f153513beeb925'),
  ('makehuman.people.masculine.outfit.male-casualsuit03.v2', '68bf136d52fc638a07cb61d79f9707c6eb80ad9699dfc4c25acd3388be465aea'),
  ('makehuman.people.masculine.outfit.male-casualsuit04.v1', '6aa1dfb2a1021694d48924c20ff8d34e2ccbd4eb88cd1a43d3119305c04e6a43'),
  ('makehuman.people.masculine.outfit.male-casualsuit04.v2', '432f14acc9369eaf1bab12fe55c36fb60177ec7b764f56f6925ba97f053e7174'),
  ('makehuman.people.masculine.outfit.male-casualsuit05.v1', '8d70e0f1627b13df021211eb7ee513d5ac0b061851643ca8b548192c304ac8ef'),
  ('makehuman.people.masculine.outfit.male-casualsuit05.v2', '9493e464b920c81da6bd9207fdc99be4e3a2d703f608d852460b41077642e6ff'),
  ('makehuman.people.masculine.outfit.male-casualsuit06.v1', '8076366a205689c8b1b6a6b6cf6b78e7c22f5651b3d4cf4f79895dd280a957a9'),
  ('makehuman.people.masculine.outfit.male-casualsuit06.v2', '3c3aaa5b18383facb6e1d0dab210236a3745f7df2dbe61831165930adc98d71b'),
  ('makehuman.people.masculine.outfit.male-elegantsuit01.v1', 'a268a615b224f6d0496edc903be2ced1d455597eecdae175b46e04c8d970b380'),
  ('makehuman.people.masculine.outfit.male-elegantsuit01.v2', 'd49b04abe2d958ae5d296ccaa126e85b86c119d64c42e75ab955c8a9ea8c49d7'),
  ('makehuman.people.masculine.outfit.male-worksuit01.v1', '215191838e81745e341b793a92b37eb9eee718f8c13db1ed0af4c45156836bde'),
  ('makehuman.people.masculine.outfit.male-worksuit01.v2', '32a4098286d97d73c2ec5d96d10f8785ef730b952922ed78fb1e7eee9d12207e'),
  ('makehuman.people.masculine.shoes.shoes01.v1', '5e3c71a2e9b001b4513026c9256bd5cc224f560154ced4e1082da945db6cc291'),
  ('makehuman.people.masculine.shoes.shoes01.v2', '85786d03b462224f66d3559434fe8208d3f719dbcec812dde8b2755203d5749b'),
  ('makehuman.people.masculine.shoes.shoes02.v1', '614f70be439acb32ca21552585a5b7ca84be4c4fabaf525d56141c7680d4e123'),
  ('makehuman.people.masculine.shoes.shoes02.v2', '205abb8cd588f3f557d2856f621e22ff730e8336625f4441d9576e2b4cf7d97c'),
  ('makehuman.people.masculine.shoes.shoes03.v1', 'd674b36cac373838c347379cacd58b2f205f86c0f709cb5d5fcd6833f4864dba'),
  ('makehuman.people.masculine.shoes.shoes03.v2', '7a52de8effc18ac66ca24f48c47ca05d3b6cd8e5f0318a3d422dc486fec69074'),
  ('makehuman.people.masculine.shoes.shoes04.v1', 'c89b55ca2baad0c9cfc239aab1339e2fe7898c3465259202d47aad127a2ad67a'),
  ('makehuman.people.masculine.shoes.shoes04.v2', '519521ff9aa404137cca813ad243b68a864c9d6de711eda5f6ab338b31b52bca'),
  ('makehuman.people.masculine.shoes.shoes05.v1', '9d11281a5f982ed4a9f203aeadd35dc313e76c593f3fd7a97df75605be91f400'),
  ('makehuman.people.masculine.shoes.shoes05.v2', '903785ea244abe84ff3c470e8a00f710a41238c4cb80de8383f9ac2c353a046d'),
  ('makehuman.people.masculine.shoes.shoes06.v1', '84770cebd23a5c58c3bd031e75e898a9651593c4deb3e0b585a5fdb573c27094'),
  ('makehuman.people.masculine.shoes.shoes06.v2', '1547d7a84f6275257dc2c8792369dc9ecc1d298317f19785429e60ce37bfb2f7'),
  ('makehuman.people.material.brows.eyebrow001.v1', 'f2affdc83785b0b7002cc21e407c65460f5f82bac0c2fa509c98dd2622c643b3'),
  ('makehuman.people.material.brows.eyebrow003.v1', '757cff1146bb81f2aff39144a9af5861338830d30abef6ebc60e1db750f2172c'),
  ('makehuman.people.material.brows.eyebrow006.v1', '8290fc63122a411f59ba5fc5871bc2775584aa8e3339cd44e996e64215abb396'),
  ('makehuman.people.material.brows.eyebrow009.v1', '7f9c79499ccedb6606ea727fb0b9380d18acbd660f55e4b2bde2e522b7b6ce62'),
  ('makehuman.people.material.brows.eyebrow010.v1', '2b84db0e7c4de1eef5e42f574874bacfc01583cc55c5882a930674ad06f474ad'),
  ('makehuman.people.material.eyecolour.blue.v1', 'eba792c327fd7c534f4c2cf995f7d3edb45106d20706511faed5438eb37e7204'),
  ('makehuman.people.material.eyecolour.brown.v1', '3e70f8832f3b1b99f847cb86b2249454257b2a8e68cd1a43445f9a9248e582eb'),
  ('makehuman.people.material.eyecolour.brown.v1', 'a87b851ce8c91d75bec983f2dbdab37daeb81dcf61acdc6953f4c64702311d8f'),
  ('makehuman.people.material.eyecolour.brownlight.v1', '51262168e8f62c0627e194c987dd0fdfac79a741590f7447c945fe6a395b9cd1'),
  ('makehuman.people.material.eyecolour.green.v1', '26a72931dcef9929c496187f51238fea2b340e5ef93ddf18bd4fae8e79de4b6e'),
  ('makehuman.people.material.eyecolour.grey.v1', '01d09b67dc6509226bac36b075a68e3229e70aa6ce8af586de2f7f39fe72af48'),
  ('makehuman.people.material.hair.afro01.v1', '477fca470ef6afde7074636016b16922cf680a8c3965833610cce60a0711d792'),
  ('makehuman.people.material.hair.afro01.v1', 'cd531415bcd9d78ca84bddb2d4762aec0ca248ecdf929ca5c7ffff1fbf6b24f0'),
  ('makehuman.people.material.hair.afro01.v1', 'cdaaef31f0ea8facb34af3d531941a734f943b943b90c574561d500c227175ed'),
  ('makehuman.people.material.hair.bob01.v1', '0d74b9131e868eb7523f03d5867724dce3e892f58c804448022797e0928ef203'),
  ('makehuman.people.material.hair.bob01.v1', '5f3ce01fa1f7ccb88595dcffb7d59a505adf061e23db1c7cbfe094d83398c3a1'),
  ('makehuman.people.material.hair.bob01.v1', '8b69e3d643ddc0639e0c996ab7f5e244d9aca5edd738fb9f1d2d8518d780b17c'),
  ('makehuman.people.material.hair.bob02.v1', '04641ab3eead270016cee46523f4df90b4028bcc23dc12feded41e737b7eec97'),
  ('makehuman.people.material.hair.bob02.v1', '6c48ca4aa0a5049addf349df6b707aacbc3b7f852bd4f9b968adc584f4067ae5'),
  ('makehuman.people.material.hair.bob02.v1', '8f263567c2a7a997e2dcfe06d6c9aae77ab693cf3ffc9136c69fa8815f712564'),
  ('makehuman.people.material.hair.braid01.v1', 'c1987f2d38b2fd4105eac5819d41e353d1f0e5edc148eb55b07f84b9ec423b20'),
  ('makehuman.people.material.hair.braid01.v1', 'd0f02a81c4e7a5c8af60094feadd0ea504604a93ecc3d2530e31cee0daa191fc'),
  ('makehuman.people.material.hair.braid01.v1', 'e4c1e463d4d9529fb8e68f2d26d66feb81623a0557a239bceafd2b3b25701070'),
  ('makehuman.people.material.hair.long01.v1', '093665a51cbf184dae0fb0788c610bd9b936bffed2b6acf2dde5b0899a684d90'),
  ('makehuman.people.material.hair.long01.v1', '2e6dfe48cb438b7f4e7aa1930cd4613e1a9fc95ce9d702dcc42d8c4bff7eb9b3'),
  ('makehuman.people.material.hair.long01.v1', '8b70809aae4e324c7e9902f47bc26e0517e75b108aa7871400e04b373628be95'),
  ('makehuman.people.material.hair.ponytail01.v1', '6ef83930abf946e40edf863878cf05d776b5b5f9c416ac7eb131bf826302f4dd'),
  ('makehuman.people.material.hair.ponytail01.v1', 'ec344dd37f0e1c66d86d41d850dc98f7c4e7b082779f11c49ba3bb5c6e87bf87'),
  ('makehuman.people.material.hair.ponytail01.v1', 'f9a3c8db9ce9150204170cd3b5273bd335baf1950b19fa0594e2d716d11154c3'),
  ('makehuman.people.material.hair.short01.v1', '66c5e805dc3c5eb7097617396e6caa9a9f3e31c4dbee93905436ce9c2784e59b'),
  ('makehuman.people.material.hair.short01.v1', 'b6c5c97b77378059104304d167cd5a31a7a470359f72a38359a4b5deced79db4'),
  ('makehuman.people.material.hair.short01.v1', 'eae0c9dcdf9b88de70c73f65425bd4d84f8ed4fa8d71dd34cfea706a441d34a5'),
  ('makehuman.people.material.hair.short02.v1', '4938654273050f0f5157e8e9a2ccc8f2582877356b2c4adc4c6cb4ca5e7ef1c7'),
  ('makehuman.people.material.hair.short02.v1', '5eb17ff3d339ecc8269121d4b839b394614476554234e52462841b2af87484ee'),
  ('makehuman.people.material.hair.short02.v1', 'c2cfc00d6478f27ccc987b8bd13c318251601abf756657fa514ce75ee8961111'),
  ('makehuman.people.material.hair.short03.v1', '403477c95ad2439ae9924b74caedbdf2dc0320b78d30bb467c5cf383f63a6e41'),
  ('makehuman.people.material.hair.short03.v1', '5b9ebbcfc2bc80419c933e17fa8557b0074984bcda9427d4bfdb8311060bad9b'),
  ('makehuman.people.material.hair.short03.v1', '92eac7eb21e209de508405846b4de0e617b276b17d7a1cf42120fcd84b6469c9'),
  ('makehuman.people.material.hair.short04.v1', '61cd4dfd7a3d4ca10ddd9ca260e6d6778a4e29b1f6d6dcd17f622a22ce1ed8d4'),
  ('makehuman.people.material.hair.short04.v1', '7599ff6fd8e250b038e944536e5a0c1b7f4f52c19a1e33e9dc0dccc8793b5329'),
  ('makehuman.people.material.hair.short04.v1', 'eed63e87217cd642bab148410e73047e916395915cde31802242b021dd6aeab7'),
  ('makehuman.people.material.lashes.eyelashes01.v1', 'ef993d547a58e308eff66eec87142fd3cf020fb9b2e2b83ec042e4888552930f'),
  ('makehuman.people.material.outfit.female-casualsuit01.v1', '8c344b7fe2d8b09e1308c6b0881194982f160642923c58a85e4bbf5e9b111ac0'),
  ('makehuman.people.material.outfit.female-casualsuit02.v1', '884e61231f9d0193e2ab9d789c6d48ba34d9b56d82eecf5b02234a6e3be8d83d'),
  ('makehuman.people.material.outfit.female-elegantsuit01.v1', 'b7e4bd0b10717704a8ccce14537f55bbb3effbf0067b5dfd643a78e841783668'),
  ('makehuman.people.material.outfit.female-sportsuit01.v1', '6a79b081de92eb7e593d2d259a05408fb98a6e9b7fdda08527b6c6609ddd6c82'),
  ('makehuman.people.material.outfit.male-casualsuit01.v1', 'a9cbd14f196830a2ff349c8cb155f596fae59f1b5f521877dbb48949a01fc490'),
  ('makehuman.people.material.outfit.male-casualsuit02.v1', '59b3c1115e3843e397fb8c5721ee5624d00110e3ce7feee5f84b18bfd5dab589'),
  ('makehuman.people.material.outfit.male-casualsuit03.v1', '42f5977f44f92c55a257fa2b0831ca0322ad7a62d2d6ef9a1e54c7d65dca770e'),
  ('makehuman.people.material.outfit.male-casualsuit04.v1', 'f3ab94882a0b7a50c287c60efa50fde7d4711c58d97d03c86e49e56e1aa0b509'),
  ('makehuman.people.material.outfit.male-casualsuit05.v1', '1b6c1eadf5471590d697ac97fbb3efc65030cd64f8fe999591e5193bceb1b8b7'),
  ('makehuman.people.material.outfit.male-casualsuit06.v1', '77480863cbefe061eacf5f73b75edc0a9107fba9c21626bd41cbd90eef876537'),
  ('makehuman.people.material.outfit.male-elegantsuit01.v1', '8dc1260b816850de6dd5a5035b982e8c867ee0c1227266307eb170afcd917d89'),
  ('makehuman.people.material.outfit.male-worksuit01.v1', '7dea7caa634676120c278b98169c0512c398933bd1abb59ac89d71b9a99192e7'),
  ('makehuman.people.material.shoes.shoes01.v1', '60fa89b95f08d8441bf4e7f4bfd3b36d61637b62047dac735d8bc6dc0278cfa3'),
  ('makehuman.people.material.shoes.shoes02.v1', 'b70338180141510bc9f0cfa36044f8c400d182f2f09ac7f29175288ffbfb0dec'),
  ('makehuman.people.material.shoes.shoes03.v1', '8df3621a621f21d5f7dfe7bfbad03c5835a442f7929f75439ad7fa528d6ef86d'),
  ('makehuman.people.material.shoes.shoes04.v1', '4a1c0cab9f5734a9c9a77f61f7b8deea2919230002cb5af4f0ecfc3cc3730f5d'),
  ('makehuman.people.material.shoes.shoes05.v1', '88e3290b4dac526ba0fbe22f713b977c00d7917961fd5b27be920de6dc168f7b'),
  ('makehuman.people.material.shoes.shoes06.v1', '0faec0e6311731cb876763434f29db781d14d1fa0ba5fd37a97c08ccf5d44e1e'),
  ('makehuman.people.material.skin.middleage-african-female.v1', '51c4cb3f6302c60e579f6583af34af87a650dab2e7879a60a00dbbde498b9627'),
  ('makehuman.people.material.skin.middleage-african-male.v1', '75d64fa43d72bbf62ee75dd9f2ea0b66e10d76a3826755a247ca19b7ab0b4e4c'),
  ('makehuman.people.material.skin.middleage-asian-female.v1', '8233132d3a6c0a6b1fd6a12d7c59613837b4803e52ad8b749cc633a182ca22d5'),
  ('makehuman.people.material.skin.middleage-asian-male.v1', '63473ac05d1a680ea63b239dcffcadb7c21a2c535a21ad5557f2b44484ecd5e1'),
  ('makehuman.people.material.skin.middleage-caucasian-female.v1', 'd68e055a124d3b6845e764793ec54f3951b43ea302358efc61e7dabe66175e7d'),
  ('makehuman.people.material.skin.middleage-caucasian-male.v1', 'd288b13ad74e72472f4ae9de5d0032259101b0914d7e0216f8b651664aa4a9af'),
  ('makehuman.people.material.skin.young-african-female.v1', '8a9f845a6f08986a1ac0716337355e7d217166831f5cdb70227eb2a1bcb5d308'),
  ('makehuman.people.material.skin.young-african-male.v1', '6e3b0bbb4d0220105b46addb005d49591a028cd5196d723572c210a9b92a3e49'),
  ('makehuman.people.material.skin.young-asian-female.v1', '7918e3e379449a6898f6946179f3998cecc123d66ae72d3039a6a4020b14e733'),
  ('makehuman.people.material.skin.young-asian-male.v1', 'c3b44b471fa69d64c9e8189c19621a5a40b9c36a4e4c74df0f7965f0eafad685'),
  ('makehuman.people.material.skin.young-caucasian-female.v1', '4c5f98e2674b485932c4127d0f475922d366542bc6b98cbc7372c21e16cb8cf1'),
  ('makehuman.people.material.skin.young-caucasian-male.v1', '635855afe61b98273ca8c6d5d6bcbda392530b7f70794a6c542cfd9e27f8075e'),
  ('quaternius.modular.casual-f.v2', '1dc3b8c8299fb90c86efdfdcceaa2a2dff2da2548004899a0ef6c4287d87d838'),
  ('quaternius.modular.casual.v2', '01caafd01d1b32a6e7dc7a7cba7e1489029f9303f02d419ffbb44e08e9d69446'),
  ('quaternius.modular.formal-f.v2', '92a2eaabccf2ffec2ad2259c4d5e91b8d95431ec9f85addc94cb97b8b12c7cea'),
  ('quaternius.modular.hoodie.v2', '7d026bd1bac1a4c2e9e4785af4a1c3ed13d0abae2c870798654f816ec8d78d2d')
);

do $$
declare
  undeclared text;
begin
  select string_agg(asset_key, ', ' order by asset_key) into undeclared
  from world_reviewed_asset where kind is null;
  if undeclared is not null then
    raise exception 'reviewed assets whose kind this migration cannot establish: %', undeclared
      using errcode = '23514',
            hint = 'Each one needs its kind declared by a migration before this one can run.';
  end if;
end $$;

alter table world_reviewed_asset alter column kind set not null;
alter table world_reviewed_asset add constraint world_reviewed_asset_kind_check
  check (kind in ('object', 'component'));

commit;
