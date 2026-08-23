"""PostGIS round-trip sanity for CustomerProfile, CourierProfile, RestaurantProfile, Address."""

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point
from sqlalchemy import select

from app.users.enums import VehicleType
from app.users.models import (
    Address,
    CourierProfile,
    CustomerProfile,
    RestaurantProfile,
)


async def _round_trip(value):
    """Convert to shapely and back; ensures GeoAlchemy2 + DB store the point correctly."""
    return to_shape(value).x, to_shape(value).y


async def test_customer_profile_point_round_trip(db_session, make_user):
    user = await make_user(db_session, email="cp@example.com")
    pt = from_shape(Point(36.8219, -1.2921), srid=4326)
    prof = CustomerProfile(user_id=user.id, current_location=pt)
    db_session.add(prof)
    await db_session.commit()
    fetched = (
        await db_session.execute(select(CustomerProfile).where(CustomerProfile.user_id == user.id))
    ).scalar_one()
    assert (
        abs(fetched.current_location is not None and to_shape(fetched.current_location).x - 36.8219)
        < 1e-6
    )
    assert abs(to_shape(fetched.current_location).y - (-1.2921)) < 1e-6


async def test_courier_profile_point_round_trip(db_session, make_user):
    user = await make_user(db_session, email="cou_pt@example.com")
    pt = from_shape(Point(2.349, 48.864), srid=4326)
    prof = CourierProfile(user_id=user.id, vehicle_type=VehicleType.bike, current_location=pt)
    db_session.add(prof)
    await db_session.commit()
    fetched = (
        await db_session.execute(select(CourierProfile).where(CourierProfile.user_id == user.id))
    ).scalar_one()
    assert abs(to_shape(fetched.current_location).x - 2.349) < 1e-6


async def test_restaurant_profile_point_round_trip(db_session, make_user):
    user = await make_user(db_session, email="r_pt@example.com")
    pt = from_shape(Point(-73.985, 40.748), srid=4326)
    prof = RestaurantProfile(
        user_id=user.id,
        restaurant_name="X",
        business_license="L-X",
        address="addr",
        location=pt,
    )
    db_session.add(prof)
    await db_session.commit()
    fetched = (
        await db_session.execute(
            select(RestaurantProfile).where(RestaurantProfile.user_id == user.id)
        )
    ).scalar_one()
    assert abs(to_shape(fetched.location).x - (-73.985)) < 1e-6


async def test_address_point_round_trip(db_session, make_user):
    user = await make_user(db_session, email="a_pt@example.com")
    pt = from_shape(Point(36.8, -1.3), srid=4326)
    addr = Address(
        user_id=user.id, label="L", street="S", city="C", phone="+14155550001", location=pt
    )
    db_session.add(addr)
    await db_session.commit()
    fetched = (
        await db_session.execute(select(Address).where(Address.user_id == user.id))
    ).scalar_one()
    x, y = await _round_trip(fetched.location)
    assert abs(x - 36.8) < 1e-6
    assert abs(y - (-1.3)) < 1e-6
