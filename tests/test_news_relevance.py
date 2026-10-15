"""Unit tests for deterministic news headline relevance and common-word collision guards."""
import pytest
from backend.tools.news_sentiment import is_headline_relevant


def test_reliance_collision_guards():
    # Negative examples (bare "reliance" in non-corporate English usage MUST be rejected)
    assert not is_headline_relevant("India's reliance on Russian oil reaches record high", "RELIANCE.NS")
    assert not is_headline_relevant("Growing reliance on artificial intelligence in healthcare", "RELIANCE.NS")
    assert not is_headline_relevant("Heavy reliance on imported fertilizers raises fiscal burden", "RELIANCE.NS")

    # Negative examples (ADAG group sister companies MUST NOT match Reliance Industries)
    assert not is_headline_relevant("Reliance Power shares hit 5% lower circuit after debt notice", "RELIANCE.NS")
    assert not is_headline_relevant("Reliance Infrastructure wins arbitration award against Delhi Metro", "RELIANCE.NS")

    # Positive examples (Reliance Industries, RIL, Reliance Jio, Reliance Retail MUST be kept)
    assert is_headline_relevant("Reliance Industries to invest Rs 75,000 crore in green energy", "RELIANCE.NS")
    assert is_headline_relevant("RIL Q4 net profit beats analyst estimates with 12% rise", "RELIANCE.NS")
    assert is_headline_relevant("Reliance Jio adds 3.5 million subscribers in March", "RELIANCE.NS")
    assert is_headline_relevant("Reliance Retail acquires stake in local fashion brand", "RELIANCE.NS")


def test_powergrid_collision_guards():
    # Negative examples (generic "power grid" in non-corporate usage MUST be rejected)
    assert not is_headline_relevant("US power grid collapses after extreme winter storm", "POWERGRID.NS")
    assert not is_headline_relevant("Texas power grid faces critical test during summer heatwave", "POWERGRID.NS")
    assert not is_headline_relevant("Cyber attack threats to national power grid infrastructure", "POWERGRID.NS")

    # Positive examples (Power Grid Corporation, Powergrid, PGCIL MUST be kept)
    assert is_headline_relevant("Power Grid Corporation secures inter-state transmission project", "POWERGRID.NS")
    assert is_headline_relevant("Powergrid Q3 net profit rises 10% to Rs 4,120 crore", "POWERGRID.NS")
    assert is_headline_relevant("PGCIL approves interim dividend of Rs 4.5 per share", "POWERGRID.NS")


def test_nestle_collision_guards():
    # Negative examples (bare global nestle without Indian corporate context)
    assert not is_headline_relevant("Nestle opens new research lab in Switzerland", "NESTLEIND.NS")
    assert not is_headline_relevant("Nestle global CEO steps down after thirty years at Swiss headquarters", "NESTLEIND.NS")

    # Positive examples (Nestle India or corporate context like Maggi, shares, results)
    assert is_headline_relevant("Nestle India reports 8% revenue growth in Q4", "NESTLEIND.NS")
    assert is_headline_relevant("Nestle launches new Maggi variants in Indian market", "NESTLEIND.NS")
    assert is_headline_relevant("Nestle shares hit 52-week high after board meeting", "NESTLEIND.NS")


def test_titan_collision_guards():
    # Negative examples (generic English "titan")
    assert not is_headline_relevant("Tech titan Apple reports record quarterly profit and sales", "TITAN.NS")
    assert not is_headline_relevant("Tech titan unveils revolutionary generative AI chip", "TITAN.NS")
    assert not is_headline_relevant("Clash of the titans in international cricket tournament", "TITAN.NS")
    assert not is_headline_relevant("OceanGate Titan submersible debris recovered from North Atlantic", "TITAN.NS")

    # Positive examples (Titan Company or jewellery/watch/Tanishq context)
    assert is_headline_relevant("Titan Company reports 20% jump in jewellery revenue", "TITAN.NS")
    assert is_headline_relevant("Titan shares rise as Tanishq expands international store count", "TITAN.NS")
    assert is_headline_relevant("Titan watch sales surge during festive season", "TITAN.NS")


def test_itc_collision_guards():
    # Negative examples (Input Tax Credit / International Trade Commission)
    assert not is_headline_relevant("Govt issues fresh guidelines on ITC claims under GST rules", "ITC.NS")
    assert not is_headline_relevant("Tax authorities detect Rs 150 crore fake ITC claims by export firms", "ITC.NS")
    assert not is_headline_relevant("ITC rules revised for exporters seeking tariff refund", "ITC.NS")

    # Positive examples (ITC Limited, ITC Ltd, or tobacco/hotel/fmcg/dividend/share context)
    assert is_headline_relevant("ITC Limited declares interim dividend of Rs 6.5 per share", "ITC.NS")
    assert is_headline_relevant("ITC Ltd board approves hotel business demerger scheme", "ITC.NS")
    assert is_headline_relevant("ITC shares rise 2% on strong cigarette volume growth", "ITC.NS")
    assert is_headline_relevant("ITC FMCG business achieves operational profitability milestone", "ITC.NS")


def test_lt_collision_guards():
    # Negative examples: bare "lt" must NEVER match (Lieutenant / Lt Governor)
    assert not is_headline_relevant("Lt Governor approves construction contract", "LT.NS")
    assert not is_headline_relevant("Lt. Governor addresses budget session of legislative assembly", "LT.NS")
    assert not is_headline_relevant("Lt Gen Sharma takes charge of Northern Command", "LT.NS")

    # Positive examples (Larsen & Toubro, Larsen and Toubro, L&T)
    assert is_headline_relevant("Larsen & Toubro wins mega offshore order from Middle East", "LT.NS")
    assert is_headline_relevant("Larsen and Toubro bags Rs 3,000 crore hydrocarbon contract", "LT.NS")
    assert is_headline_relevant("L&T construction arm bags Rs 5,000 crore hydrocarbon contract", "LT.NS")


def test_jswsteel_collision_guards():
    # Negative examples: sister companies and non-flagship projects must be rejected
    assert not is_headline_relevant("JSW Infrastructure completes slurry pipeline business from JSW Utkal Steel for around Rs 1 , 617 crore", "JSWSTEEL.NS")
    assert not is_headline_relevant("JSW Energy commissions 300 MW wind project in Karnataka", "JSWSTEEL.NS")

    # Positive examples: JSW Steel, or JSW + steel within 3 words
    assert is_headline_relevant("JSW Steel reports 12% rise in crude steel production", "JSWSTEEL.NS")
    assert is_headline_relevant("JSW to expand steel capacity by 5 million tonnes in Vijayanagar", "JSWSTEEL.NS")


def test_bank_acronyms_and_disambiguation():
    # SBI negative vs positive
    assert not is_headline_relevant("SBI (Small Business Indicator) falls across European economies", "SBIN.NS")
    assert not is_headline_relevant("SBI Card reports 8% drop in quarterly profit as credit costs rise", "SBIN.NS")
    assert not is_headline_relevant("SBI Life gross written premium increases 14% to Rs 25,000 crore", "SBIN.NS")
    assert is_headline_relevant("State Bank of India reduces home loan interest rates", "SBIN.NS")
    assert is_headline_relevant("SBI shares surge after quarterly net profit beats estimates", "SBIN.NS")

    # HDFC Bank
    assert not is_headline_relevant("Axis Bank increases ATM fees starting July 1", "HDFCBANK.NS")
    assert not is_headline_relevant("HDFC Life reports 15% increase in annual net premium income", "HDFCBANK.NS")
    assert not is_headline_relevant("HDFC AMC quarterly average AUM surges past Rs 5 lakh crore", "HDFCBANK.NS")
    assert is_headline_relevant("HDFC Bank expands digital banking services for retail users", "HDFCBANK.NS")
    assert is_headline_relevant("HDFC Bank to acquire additional stake in HDFC Life", "HDFCBANK.NS")

    # ICICI Bank
    assert not is_headline_relevant("ICICI Prudential Life net profit falls 25% on higher policyholder payouts", "ICICIBANK.NS")
    assert not is_headline_relevant("ICICI Lombard general insurance premium income up 16% in Q2", "ICICIBANK.NS")
    assert is_headline_relevant("ICICI Bank Q4 net profit jumps 17% on strong retail loan growth", "ICICIBANK.NS")

    # Kotak Bank
    assert not is_headline_relevant("Kotak Life Insurance launches new guaranteed pension plan", "KOTAKBANK.NS")
    assert is_headline_relevant("Kotak Mahindra Bank appoints new managing director and CEO", "KOTAKBANK.NS")

    # Axis Bank
    assert not is_headline_relevant("Earth's rotational axis tilts slightly due to groundwater depletion", "AXISBANK.NS")
    assert not is_headline_relevant("Axis Mutual Fund launches new manufacturing index fund", "AXISBANK.NS")
    assert is_headline_relevant("Axis Bank credit card reward rules updated for new fiscal year", "AXISBANK.NS")


def test_conglomerate_sister_company_guards():
    # Bajaj Finance vs Bajaj Auto / Electricals
    assert not is_headline_relevant("Bajaj Auto monthly motorcycle sales cross 3.5 lakh units", "BAJFINANCE.NS")
    assert not is_headline_relevant("Bajaj Electricals posts lower quarterly margin on consumer weakness", "BAJFINANCE.NS")
    assert is_headline_relevant("Bajaj Finance quarterly customer franchise expands by 3.8 million", "BAJFINANCE.NS")
    assert is_headline_relevant("Bajaj Finserv consolidated net profit grows 18% in Q3", "BAJFINANCE.NS")

    # Tata Steel vs Tata Motors / Tata Power
    assert not is_headline_relevant("Tata Motors global vehicle wholesales increase by 8% in Q3", "TATASTEEL.NS")
    assert not is_headline_relevant("Tata Power commissions 400 MW solar project in Rajasthan", "TATASTEEL.NS")
    assert is_headline_relevant("Tata Steel completes blast furnace relining at Kalinganagar plant", "TATASTEEL.NS")


def test_other_candiate_disambiguations():
    # TCS vs Tax Collected at Source
    assert not is_headline_relevant("Finance Ministry levies 20% TCS on overseas tour packages under LRS", "TCS.NS")
    assert is_headline_relevant("TCS wins $1 billion multi-year IT services contract from European bank", "TCS.NS")
    assert is_headline_relevant("Tata Consultancy Services announces wage hikes for employees", "TCS.NS")

    # NTPC vs RRB Railway Exams
    assert not is_headline_relevant("RRB NTPC admit card 2025 released for computer-based typing test", "NTPC.NS")
    assert is_headline_relevant("NTPC commissions 500 MW solar capacity at Fatehgarh plant", "NTPC.NS")
    assert is_headline_relevant("National Thermal Power Corporation reports record annual generation", "NTPC.NS")

    # Maruti vs Maruti Mandir/Temple
    assert not is_headline_relevant("Lakhs of devotees visit historic Maruti temple on Hanuman Jayanti", "MARUTI.NS")
    assert is_headline_relevant("Maruti car sales jump 12% in April led by SUV demand", "MARUTI.NS")
    assert is_headline_relevant("Maruti Suzuki commences export of Fronx SUV to Japan", "MARUTI.NS")

    # Sun Pharma (bare "sun" rejected)
    assert not is_headline_relevant("Sun shines bright over New Delhi during dry winter week", "SUNPHARMA.NS")
    assert not is_headline_relevant("Sun Life Financial expands asset management business in Asia", "SUNPHARMA.NS")
    assert is_headline_relevant("Sun Pharma receives US FDA approval for generic dermatological drug", "SUNPHARMA.NS")

    # Asian Paints (bare "Asian" rejected)
    assert not is_headline_relevant("Asian markets slump as rising crude oil prices weigh on sentiment", "ASIANPAINT.NS")
    assert is_headline_relevant("Asian Paints cuts prices as raw material inflation cools", "ASIANPAINT.NS")


def test_regional_language_and_malformed_rejection():
    # Hindi / Gujarati non-English text must be rejected even if containing English words
    hindi_headline = "Axis Bank ने ATM चार्ज बढ़ाए , 1 जुलाई 2025 से लागू होंगे नए नियम"
    assert not is_headline_relevant(hindi_headline, "AXISBANK.NS", lang="Hindi")

    gujarati_headline = "નિફ્ટી ફ્યુચર ૨૪૬૦૬ પોઈન્ટ ઉપર જ તેજી તરફી ધ્યાન"
    assert not is_headline_relevant(gujarati_headline, "HDFCBANK.NS", lang="Gujarati")

    # Empty headline
    assert not is_headline_relevant("", "RELIANCE.NS")
