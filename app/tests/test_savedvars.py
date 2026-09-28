from azerothgps.savedvars.parser import loads

SAMPLE = r'''
AzerothGPS_LinkDB = {
	["version"] = 1,
	["settings"] = {
		["beacon"] = true,
		["corner"] = "tl",
		["hz"] = 15,
	},
	["probes"] = {
		{
			["reason"] = "manual",
			["results"] = {
				{
					["name"] = "GetUnitSpeed",
					["value"] = "7, 7, 4.5, 4.72",
					["ok"] = true,
				}, -- [1]
			},
		}, -- [1]
	},
	["chars"] = {
		["Realm-Name"] = {
			["taxiNodes"] = {
				[1414] = { ["nodes"] = { { ["x"] = 0.5, ["name"] = "Orgrimmar, \"Durotar\"" } } },
			},
			["flights"] = {},
		},
	},
	["neg"] = -1.5e-3,
	["nothing"] = nil,
}
Other = 3
'''


def test_parse_sample():
    d = loads(SAMPLE)
    db = d["AzerothGPS_LinkDB"]
    assert db["settings"] == {"beacon": True, "corner": "tl", "hz": 15}
    assert db["probes"][0]["results"][0]["value"] == "7, 7, 4.5, 4.72"
    node = db["chars"]["Realm-Name"]["taxiNodes"][1414]["nodes"][0]
    assert node["name"] == 'Orgrimmar, "Durotar"'
    assert db["neg"] == -1.5e-3
    assert d["Other"] == 3
