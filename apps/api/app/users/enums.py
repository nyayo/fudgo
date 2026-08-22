"""Shared string-backed enums for the users domain."""

import enum


class UserType(str, enum.Enum):
    customer = "customer"
    courier = "courier"
    restaurant = "restaurant"
    restaurant_staff = "restaurant_staff"


class AuthProvider(str, enum.Enum):
    email = "email"
    phone = "phone"
    google = "google"
    github = "github"
    linkedin = "linkedin"


class VehicleType(str, enum.Enum):
    bike = "bike"
    motorcycle = "motorcycle"
    car = "car"


class StaffRole(str, enum.Enum):
    manager = "manager"
    waiter = "waiter"
    cashier = "cashier"


class DevicePlatform(str, enum.Enum):
    android = "android"
    ios = "ios"
    web = "web"
