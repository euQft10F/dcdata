from dcdata.csvio import read_csv, write_csv


def test_roundtrip_and_formatting(tmp_path):
    p = tmp_path / "o.csv"
    n = write_csv([{"a": 1, "b": True, "c": None, "d": 'x,"y"', "extra": 9}], p, ["a", "b", "c", "d"])
    assert n == 1
    raw = p.read_bytes()
    assert raw == b'a,b,c,d\n1,true,,"x,""y"""\n'
    assert read_csv(p) == [{"a": "1", "b": "true", "c": "", "d": 'x,"y"'}]
