from app.ml import predictor, water_quality
print("3-class available:", water_quality.is_available())
for n, f in [("excellent",{"ph":7.0,"turbidity":0.5,"tds":120.0,"temperature":15.0,"dissolved_oxygen":9.5}),
             ("typical",{"ph":7.1,"turbidity":1.2,"tds":280.0,"temperature":18.0,"dissolved_oxygen":8.4}),
             ("poor",{"ph":5.2,"turbidity":60.0,"tds":3200.0,"temperature":32.0,"dissolved_oxygen":2.5}),
             ("borderline",{"ph":7.0,"turbidity":12.0,"tds":700.0,"temperature":24.0,"dissolved_oxygen":5.5})]:
    r = predictor.predict(f)
    print(n, "| risk=", r["risk_level"], "conf=", r["confidence"],
          "p_potable=", r["probability_potable"], "p_not=", r["probability_not_potable"])
    if water_quality.is_available():
        rr = water_quality.predict(f)
        print("   raw3:", rr["label"], rr["confidence"], rr["probabilities"])
